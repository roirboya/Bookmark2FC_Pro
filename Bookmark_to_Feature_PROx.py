# c@ Houston Engineering Inc, 2021. a@ nirby
# ----------------------------------------------------------------------------
# Import modules
import arcpy, os, csv
import pandas as pd
# ----------------------------------------------------------------------------
# Get Parameters and create blank feature
bkmk = arcpy.GetParameterAsText(0) # File - Filtered to .bkmx
output_dir = arcpy.GetParameterAsText(1) # Folder
output_name = arcpy.GetParameterAsText(2) # String - "include .shp"
coordsys = arcpy.GetParameterAsText(3) # Coord System of Dataframe, or something else if bookmarks are from another source. 
arcpy.management.CreateFeatureclass(output_dir,output_name,'POLYGON',"","DISABLED","DISABLED",coordsys)
# ----------------------------------------------------------------------------
# Load bookmarks and obtain bounding coordinates
with open(bkmk,'r') as f:
    SList = [line.strip() for line in f]
    XMIN = [x[9:-1] for x in SList if x[1:5]=='xmin']
    YMIN = [x[9:-1] for x in SList if x[1:5]=='ymin']
    XMAX = [x[9:-1] for x in SList if x[1:5]=='xmax']    
    YMAX = [x[9:-1] for x in SList if x[1:5]=='ymax']
    NAME = [x[10:-2] for x in SList if x[1:5]=='name']
# ----------------------------------------------------------------------------
for x in range(len(XMIN)):
    # Create dataframe and export to csv
    df1=pd.DataFrame([[XMIN[x],YMIN[x]], [XMIN[x],YMAX[x]], [XMAX[x],YMIN[x]], [XMAX[x],YMAX[x]]], columns=list('XY'))
    df1.to_csv(output_dir+r'\temporary__points__.csv', index=False)
    # Create points from csv, convert to rectangles, and append to output feature
    arcpy.management.XYTableToPoint(output_dir+r'\temporary__points__.csv', output_dir+r'\temporary__shapefile__.shp', "X", "Y", None, coordsys)
    arcpy.management.MinimumBoundingGeometry(output_dir+r'\temporary__shapefile__.shp', output_dir+r'\temporary__shapefile__2.shp', "RECTANGLE_BY_AREA", "ALL", None, "NO_MBG_FIELDS")
    arcpy.management.Append([output_dir+r'\temporary__shapefile__2.shp'],output_dir+r'\\'+output_name,"NO_TEST")
    # Delete intermediate data
    arcpy.management.Delete(output_dir+r'\temporary__shapefile__2.shp')
    arcpy.management.Delete(output_dir+r'\temporary__shapefile__.shp')
    os.remove(output_dir+r'\temporary__points__.csv')
# ----------------------------------------------------------------------------
# Join "bkmk_name" field based on FID
df2 = pd.concat([pd.DataFrame([NAME[i]],columns=['N']) for i in range(len(NAME))],ignore_index=True)
df2.index.name = 'bkmk_index'
df2.to_csv(output_dir+r'\temporary__points__.csv', index=True)
arcpy.management.JoinField(output_dir+r'\\'+output_name,"FID",output_dir+r'\temporary__points__.csv',"bkmk_index",["N"])
os.remove(output_dir+r'\temporary__points__.csv')
# ----------------------------------------------------------------------------