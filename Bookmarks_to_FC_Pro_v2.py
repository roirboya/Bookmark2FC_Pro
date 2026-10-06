# c@ Houston Engineering Inc, 2021. a@ nirby
"""Convert ArcGIS Pro 2D bookmarks to a polygon map-series index.

Run as a script tool inside ArcGIS Pro with a 2D map tab active.
Parameters (zero-based):
    0  Bookmark File             File, Input, Optional; filter: bkmx
    1  Use Active Map Bookmarks  Boolean, Input, Required; default: True
    2  Output Feature Class     Feature Class, Output, Required

Use a .shp path or a feature class path in an existing file geodatabase.
Title_ and Subtitle_ are Text(500) in a geodatabase, Text(254) in a shapefile.
Polygons represent the stored bookmark bounding extents, as in the original
script; rotation is stored separately, not applied to the polygons.
"""

import json
import math
import os
import tempfile

import arcpy


def load_bookmarks(bookmark_file, use_active_map, active_map):
    """Read both sources through the same bookmark-file JSON workflow."""
    if use_active_map:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "bookmarks.bkmx")
            active_map.exportBookmarks(path)
            with open(path, encoding="utf-8-sig") as stream:
                return json.load(stream)
    if not bookmark_file:
        raise ValueError("Select a .bkmx file or check Use Active Map Bookmarks.")
    with open(bookmark_file, encoding="utf-8-sig") as stream:
        return json.load(stream)


def bookmark_row(bookmark, number, total, document_sr, output_sr, is_shapefile):
    """Create geometry and attributes without intermediate datasets or joins."""
    name = bookmark.get("name") or "Bookmark {}".format(number)
    location = bookmark.get("location") or bookmark.get("extent") or {}
    try:
        xmin, ymin, xmax, ymax = (
            float(location[key]) for key in ("xmin", "ymin", "xmax", "ymax")
        )
    except (KeyError, TypeError, ValueError):
        raise ValueError("Bookmark {!r} has no valid 2D bounding extent.".format(name))
    if not all(math.isfinite(v) for v in (xmin, ymin, xmax, ymax)) or (
        xmin >= xmax or ymin >= ymax
    ):
        raise ValueError("Bookmark {!r} has an invalid bounding extent.".format(name))

    source_sr = location.get("spatialReference") or document_sr
    if not source_sr:
        raise ValueError(
            "Bookmark {!r} has no coordinate system. Export a new .bkmx "
            "from its source map and try again.".format(name)
        )
    polygon = arcpy.AsShape({
        "rings": [[[xmin, ymin], [xmin, ymax], [xmax, ymax],
                   [xmax, ymin], [xmin, ymin]]],
        "spatialReference": source_sr,
    }, True)
    if polygon.spatialReference.name == "Unknown":
        raise ValueError("Bookmark {!r} has an unknown coordinate system.".format(name))
    if polygon.spatialReference.exportToString() != output_sr.exportToString():
        transforms = arcpy.ListTransformations(
            polygon.spatialReference, output_sr, polygon.extent
        )
        transform = transforms[0] if transforms else ""
        if transform:
            arcpy.AddMessage("{}: geographic transformation {}".format(name, transform))
        polygon = polygon.projectAs(output_sr, transform)

    camera = bookmark.get("camera") or {}
    if camera.get("pitch", -90.0) != -90.0 or camera.get("roll", 0.0) != 0.0:
        raise ValueError("Bookmark {!r} is not a 2D, top-down bookmark.".format(name))
    # Convert saved CIM camera heading to the displayed map rotation sign.
    # Omitted heading defaults to north-up (0); preserve zero without -0.0.
    heading = float(camera.get("heading", 0.0))
    rotation = -heading if heading else 0.0
    if not math.isfinite(rotation):
        raise ValueError("Bookmark {!r} has an invalid rotation.".format(name))
    scale = camera.get("scale")
    if scale is None:
        # Shapefiles cannot store numeric NULL; 0 marks an unavailable scale.
        scale = 0 if is_shapefile else None
        arcpy.AddWarning("{}: no saved scale; scale_ will be blank or 0.".format(name))
    else:
        value = float(scale)
        if not math.isfinite(value) or value <= 0:
            raise ValueError("Bookmark {!r} has an invalid scale.".format(name))
        scale = max(1, int(math.floor(value + 0.5)))
        if scale > 2147483647:
            raise ValueError("Bookmark {!r}: scale exceeds the Long field limit.".format(name))

    name_length = 254 if is_shapefile else 500
    if len(name) > name_length:
        arcpy.AddWarning("{}: PageName shortened to {} characters.".format(name, name_length))
    return (polygon, name[:name_length], scale, rotation, number,
            "{} of {}".format(number, total), "", "")


def main():
    arcpy.AddMessage("Bookmarks to Feature Class v2.2 started.")
    bookmark_file = arcpy.GetParameterAsText(0)
    use_active_map = bool(arcpy.GetParameter(1))
    output = arcpy.GetParameterAsText(2)

    project = arcpy.mp.ArcGISProject("CURRENT")
    active_map = project.activeMap
    if active_map is None or active_map.mapType != "MAP":
        raise ValueError("Activate a 2D map tab before running this tool.")
    output_sr = active_map.spatialReference
    if output_sr.name == "Unknown":
        raise ValueError("Set the active map's coordinate system before running the tool.")
    if not output:
        raise ValueError("Specify an output shapefile or geodatabase feature class.")
    output = os.path.abspath(output)
    workspace, name = os.path.split(output)
    is_shapefile = output.lower().endswith(".shp")
    if not arcpy.Exists(workspace):
        raise ValueError("The output folder or geodatabase must already exist.")
    if is_shapefile:
        if not os.path.isdir(workspace) or ".gdb" in workspace.lower():
            raise ValueError("Save a shapefile in a folder, outside a geodatabase.")
    elif not workspace.lower().endswith(".gdb"):
        raise ValueError("Use a .shp filename or a feature class directly inside a .gdb.")
    arcpy.AddMessage("Requested output: {}".format(output))

    document = load_bookmarks(bookmark_file, use_active_map, active_map)
    bookmarks = document.get("bookmarks") or []
    if not bookmarks:
        raise ValueError("The selected source contains no bookmarks.")
    arcpy.AddMessage("Processing {} bookmarks.".format(len(bookmarks)))
    # Validate all bookmarks before creating or replacing an output.
    rows = [bookmark_row(b, i, len(bookmarks), document.get("spatialReference"),
                         output_sr, is_shapefile)
            for i, b in enumerate(bookmarks, 1)]

    result = arcpy.management.CreateFeatureclass(
        workspace, name, "POLYGON", spatial_reference=output_sr,
        has_m="DISABLED", has_z="DISABLED"
    )
    # Use the path actually returned by ArcGIS rather than assuming the result.
    output = str(result.getOutput(0))
    if not arcpy.Exists(output):
        raise RuntimeError("CreateFeatureclass did not create the output: {}".format(output))
    output = arcpy.Describe(output).catalogPath
    text_length = 254 if is_shapefile else 500
    arcpy.management.AddField(output, "PageName", "TEXT", field_length=text_length)
    for field, field_type in (("scale_", "LONG"), ("rotation_", "DOUBLE"),
                              ("order_", "LONG")):
        arcpy.management.AddField(output, field, field_type)
    arcpy.management.AddField(output, "pgnum_t", "TEXT", field_length=50)
    for field in ("Title_", "Subtitle_"):
        arcpy.management.AddField(output, field, "TEXT", field_length=text_length)
    # CreateFeatureclass adds an Id field to empty shapefiles; remove it only
    # after the requested fields exist. Required FID/OBJECTID fields remain.
    if is_shapefile:
        id_fields = [f.name for f in arcpy.ListFields(output)
                     if f.name.lower() == "id" and not f.required]
        if id_fields:
            arcpy.management.DeleteField(output, id_fields)
        arcpy.AddWarning("Shapefile text fields are limited to 254; use a .gdb for 500.")

    fields = ["SHAPE@", "PageName", "scale_", "rotation_", "order_",
              "pgnum_t", "Title_", "Subtitle_"]
    with arcpy.da.InsertCursor(output, fields) as cursor:
        for row in rows:
            cursor.insertRow(row)

    count = int(arcpy.management.GetCount(output).getOutput(0))
    if count != len(rows):
        raise RuntimeError("Expected {} polygons but found {} in {}.".format(
            len(rows), count, output
        ))

    # Explicitly add the result even if automatic geoprocessing output is off.
    if not any(layer.supports("DATASOURCE") and
               os.path.normcase(layer.dataSource) == os.path.normcase(output)
               for layer in active_map.listLayers()):
        active_map.addDataFromPath(output)
    arcpy.SetParameterAsText(2, output)
    arcpy.AddMessage("Verified output: {} polygons in {}.".format(count, output))


# This file is the script-tool entry point, including when code is embedded
# in a toolbox. Execute directly rather than depending on __name__.
try:
    main()
except Exception as error:
    arcpy.AddError(str(error))
    raise
