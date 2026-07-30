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

TARGET_NAMES = ["3D EMISSÃO", "3D NAVIS"]
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
# PHASE 1: STATIC VIEW & GROUP CLEANUP (COUPLED FROM YOUR PROVEN CODE)
# =========================================================================
# Collect IDs statically at the very beginning to prevent memory reference corruption
view_ids = FilteredElementCollector(doc).OfClass(View).ToElementIds()

TransactionManager.Instance.EnsureInTransaction(doc)

for v_id in view_ids:
    try:
        view = doc.GetElement(v_id)
        if view is None:
            continue
            
        # Safety gate for schedules and internal browser system views
        if view.ViewType in [ViewType.Schedule, ViewType.Internal, ViewType.ProjectBrowser, ViewType.DrawingSheet]:
            continue
            
        # Rule A: Purge View Templates (Protecting target emission templates if they already exist)
        if view.IsTemplate:
            v_name_upper = view.Name.upper()
            if not any(target in v_name_upper for target in TARGET_NAMES):
                doc.Delete(v_id)
                templates_deleted += 1
            continue 

        # Rule B: Process legitimate graphic views (2D & 3D)
        valid_view_types = [
            ViewType.FloorPlan, ViewType.CeilingPlan, ViewType.Elevation, 
            ViewType.Section, ViewType.Detail, ViewType.ThreeD, ViewType.EngineeringPlan
        ]
        
        if view.ViewType in valid_view_types:
            v_name_upper = view.Name.upper()
            
            # If it is one of the target 3D delivery views, skip and protect
            if any(target in v_name_upper for target in TARGET_NAMES):
                created_elements_ids.Add(v_id)
                continue 
                
            # Check Identity Data compliance for 2D views (Sheet Name & Sheet Number presence)
            p_num = view.LookupParameter("Sheet Number")
            p_name = view.LookupParameter("Sheet Name")
            
            s_num = p_num.AsString() if p_num else None
            s_name = p_name.AsString() if p_name else None
            
            has_sheet_conformity = False
            if s_num and s_num != "" and s_num != "---" and s_num != "-":
                if s_name and s_name != "" and s_name != "---" and s_name != "-":
                    has_sheet_conformity = True
            
            # Enforce strict deletion: If a view is 3D (not protected) or a 2D view with no sheet identity, delete it
            if view.ViewType == ViewType.ThreeD or not has_sheet_conformity:
                if view.CanBeDeleted():
                    doc.Delete(v_id)
                    views_deleted += 1
                    
    except: pass

# Purge Model and Detail Groups from Project Browser
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
# PHASE 2: STATIC MANAGE LINKS CLEANUP (COUPLED FROM YOUR PROVEN CODE)
# =========================================================================
TransactionManager.Instance.EnsureInTransaction(doc)

# 1. Process Revit Links (Unload legit RVTs, Hard Delete IFC links)
rvt_links = FilteredElementCollector(doc).OfClass(RevitLinkType).ToElements()
for link in rvt_links:
    if not link.IsNestedLink:
        try:
            l_name = link.Name.lower()
            if l_name.endswith(".rvt"):
                if link.GetLinkedFileStatus() == LinkedFileStatus.Loaded:
                    link.Unload(None)
                    rvt_unloaded += 1
            elif ".ifc" in l_name:
                doc.Delete(link.Id)
                links_removed += 1
        except: pass

# 2. Hard Delete CAD Links (DWG, DXF, DGN) using static ID collection
cad_types = FilteredElementCollector(doc).OfClass(CADLinkType).ToElementIds()
for c_id in cad_types:
    try:
        doc.Delete(c_id)
        links_removed += 1
    except: pass

# 3. Hard Delete Point Clouds using static ID collection
point_clouds = FilteredElementCollector(doc).OfClass(PointCloudType).ToElementIds()
for p_id in point_clouds:
    try:
        doc.Delete(p_id)
        links_removed += 1
    except: pass

# 4. Hard Delete Coordination Models (Navisworks NWD/NWC) using static ID collection
coord_models = FilteredElementCollector(doc).OfClass(CoordinationModelType).ToElementIds()
for co_id in coord_models:
    try:
        doc.Delete(co_id)
        links_removed += 1
    except: pass

# 5. Hard Delete Topography Links using static ID collection
topo_links = FilteredElementCollector(doc).OfClass(TopographyLinkType).ToElementIds()
for t_id in topo_links:
    try:
        doc.Delete(t_id)
        links_removed += 1
    except: pass

# 6. Hard Delete loose imported CAD or DWG elements (ImportInstance)
import_instances = FilteredElementCollector(doc).OfClass(ImportInstance).ToElementIds()
for inst_id in import_instances:
    try:
        doc.Delete(inst_id)
        links_removed += 1
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
        view_3d = next((v for v in existing_3d_views if v.Name.upper() == name), None)
        
        # Build delivery view if missing after cleanup phase
        if not view_3d and view_3d_family_type:
            view_3d = View3D.CreateIsometric(doc, view_3d_family_type.Id)
            view_3d.Name = name
            
        if view_3d:
            created_elements_ids.Add(view_3d.Id)
            template = next((t for t in all_templates if t.Name.upper() == name), None)
            
            # Build and match homonymous View Template
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
# PHASE 4: RECURSIVE SUPER PURGE (CASCADING DATABASE OPTIMIZATION)
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
# FINAL ENGINE REPORT LOG
# =========================================================================
report_log = [
    "ALVES AEC TECH - PIPELINE PROCESSOR EXECUTED SUCCESSFULLY",
    "------------------------------------------------------------",
    "• Non-compliant architectural/structural views purged: {}".format(views_deleted),
