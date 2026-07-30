# -*- coding: utf-8 -*-
import sys
import clr

# Import Revit API Elements
clr.AddReference('RevitAPI')
from Autodesk.Revit.DB import *

# Import Dynamo Document and Transaction Services
clr.AddReference('RevitServices')
import RevitServices
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager

# Import System for .NET Collections
clr.AddReference('System')
import System
from System.Collections.Generic import HashSet

# INITIALIZATION
doc = DocumentManager.Instance.CurrentDBDocument

# Reporting counters for the final performance log output
groups_deleted = 0
views_deleted = 0
templates_deleted = 0
rvt_unloaded = 0
links_removed = 0
total_purged = 0

TARGET_NAMES = ["3D EMISSAO", "3D NAVIS"]
created_elements_ids = HashSet[ElementId]()

# =========================================================================
# HELPER FUNCTION: CONFIGURATION OF CROP BOX, ANNOTATIONS, AND WORKSETS
# =========================================================================
def apply_strict_filters(document, view_or_template):
    if not view_or_template:
        return
    try:
        view_or_template.CropBoxActive = False
        view_or_template.CropBoxVisible = False
        view_or_template.AreAnnotationCategoriesHidden = True
        
        if document.IsWorkshared:
            worksets_collector = FilteredWorksetCollector(document).OfKind(WorksetKind.UserWorkset)
            for wk in worksets_collector:
                if "(HIDE)" in wk.Name.upper():
                    view_or_template.SetWorksetVisibility(wk.Id, WorksetVisibility.Hidden)
    except: pass

# =========================================================================
# PHASE 1: STATIC VIEW & GROUP CLEANUP (YOUR PROVEN METHOD)
# =========================================================================
view_ids = FilteredElementCollector(doc).OfClass(View).ToElementIds()

TransactionManager.Instance.EnsureInTransaction(doc)

for v_id in view_ids:
    try:
        view = doc.GetElement(v_id)
        if view is None:
            continue
            
        if view.ViewType in [ViewType.Schedule, ViewType.Internal, ViewType.ProjectBrowser, ViewType.DrawingSheet]:
            continue
            
        if view.IsTemplate:
            v_name_upper = view.Name.upper().replace("CAO", "CAO")
            if not any(target in v_name_upper for target in TARGET_NAMES):
                doc.Delete(v_id)
                templates_deleted += 1
            continue 

        valid_view_types = [
            ViewType.FloorPlan, ViewType.CeilingPlan, ViewType.Elevation, 
            ViewType.Section, ViewType.Detail, ViewType.ThreeD, ViewType.EngineeringPlan
        ]
        
        if view.ViewType in valid_view_types:
            v_name_upper = view.Name.upper()
            
            if "3D EMIS" in v_name_upper or "3D NAVIS" in v_name_upper:
                created_elements_ids.Add(v_id)
                continue 
                
            p_num = view.LookupParameter("Sheet Number")
            p_name = view.LookupParameter("Sheet Name")
            
            s_num = p_num.AsString() if p_num else None
            s_name = p_name.AsString() if p_name else None
            
            has_sheet_conformity = False
            if s_num and s_num != "" and s_num != "---" and s_num != "-":
                if s_name and s_name != "" and s_name != "---" and s_name != "-":
                    has_sheet_conformity = True
            
            if view.ViewType == ViewType.ThreeD or not has_sheet_conformity:
                if view.CanBeDeleted():
                    doc.Delete(v_id)
                    views_deleted += 1
                    
    except: pass

try:
    group_ids = FilteredElementCollector(doc).OfClass(GroupType).ToElementIds()
    for g_id in group_ids:
        try:
            doc.Delete(g_id)
            groups_deleted += 1
        except: pass
except: pass

TransactionManager.Instance.TransactionTaskDone()

# =========================================================================
# PHASE 2: STATIC MANAGE LINKS CLEANUP (BLINDED AGAINST PROPERTY CRASHES)
# =========================================================================
TransactionManager.Instance.EnsureInTransaction(doc)

# Use static ElementId collection to prevent CPython reference leaks on links
link_ids = FilteredElementCollector(doc).OfClass(RevitLinkType).ToElementIds()

for l_id in link_ids:
    try:
        link = doc.GetElement(l_id)
        if link is None:
            continue
            
        # Using Element.Name property to safely fetch internal name strings
        link_name = Element.Name.GetValue(link).lower()
        
        if link_name.endswith(".rvt") and not link.IsNestedLink:
            if link.GetLinkedFileStatus() == LinkedFileStatus.Loaded:
                link.Unload(None)
                rvt_unloaded += 1
        elif ".ifc" in link_name:
            doc.Delete(l_id)
            links_removed += 1
    except: pass

# Process specific element type collections via isolated blocks
link_categories = [CADLinkType, PointCloudType, CoordinationModelType, TopographyLinkType]
for cat in link_categories:
    try:
        cat_ids = FilteredElementCollector(doc).OfClass(cat).ToElementIds()
        for c_id in cat_ids:
            try:
                doc.Delete(c_id)
                links_removed += 1
            except: pass
    except: pass

try:
    import_instances = FilteredElementCollector(doc).OfClass(ImportInstance).ToElementIds()
    for inst_id in import_instances:
        try:
            doc.Delete(inst_id)
            links_removed += 1
        except: pass
except: pass

TransactionManager.Instance.TransactionTaskDone()

# =========================================================================
# PHASE 3: GENERATE, LINK, AND CONFIGURE TARGET DELIVERY VIEWS & TEMPLATES
# =========================================================================
TransactionManager.Instance.EnsureInTransaction(doc)
try:
    view_3d_types = FilteredElementCollector(doc).OfClass(ViewFamilyType).ToElements()
    view_3d_family_type = next((t for t in view_3d_types if t.ViewFamily == ViewFamily.ThreeD), None)
    
    existing_3d_views = FilteredElementCollector(doc).OfClass(View3D).ToElements()
    all_templates = [v for v in FilteredElementCollector(doc).OfClass(View).ToElements() if v.IsTemplate]
    
    for name in TARGET_NAMES:
        view_3d = next((v for v in existing_3d_views if v.Name.upper().replace("ISSAO", "ISSAO") == name), None)
        
        if not view_3d and view_3d_family_type:
            view_3d = View3D.CreateIsometric(doc, view_3d_family_type.Id)
            view_3d.Name = name
            
        if view_3d:
            created_elements_ids.Add(view_3d.Id)
            template = next((t for t in all_templates if t.Name.upper().replace("ISSAO", "ISSAO") == name), None)
            
            if not template:
                template = view_3d.CreateViewTemplate()
                template.Name = name
                
            if template:
                created_elements_ids.Add(template.Id)
                view_3d.ViewTemplateId = template.Id
                apply_strict_filters(doc, template)
                
            apply_strict_filters(doc, view_3d)
except: pass
TransactionManager.Instance.TransactionTaskDone()

# =========================================================================
# PHASE 4: RECURSIVE SUPER PURGE (DATABASE GARBAGE COLLECTION)
# =========================================================================
loop_safety = 0
max_loops = 10 

while loop_safety < max_loops:
    TransactionManager.Instance.EnsureInTransaction(doc)
    try:
        unused_ids = doc.GetUnusedElements(System.Collections.Generic.HashSet[ElementId]())
    except:
        TransactionManager.Instance.TransactionTaskDone()
        break
    
    if not unused_ids or unused_ids.Count == 0:
        TransactionManager.Instance.TransactionTaskDone()
        break 
        
    purged_this_loop = 0
    for e_id in unused_ids:
        try:
            doc.Delete(e_id)
            purged_this_loop += 1
            total_purged += 1
        except: pass
            
    TransactionManager.Instance.TransactionTaskDone()
    if purged_this_loop == 0:
        break
    loop_safety += 1

# =========================================================================
# OUTPUT DIRECT ASSIGNMENT
# =========================================================================
OUT = "SUCCESS"
