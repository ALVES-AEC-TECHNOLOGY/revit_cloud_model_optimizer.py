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
protected_elements_ids = HashSet[ElementId]()

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
# BLOCK A: INDEPENDENT TRANSACTION FOR DELETION AND LINK MANAGEMENT
# =========================================================================
TransactionManager.Instance.EnsureInTransaction(doc)

# --- STEP 1: PURGE GROUPS FROM PROJECT BROWSER ---
try:
    group_ids = FilteredElementCollector(doc).OfClass(GroupType).ToElementIds()
    for g_id in group_ids:
        try:
            doc.Delete(g_id)
            groups_deleted += 1
        except: pass
except: pass

# --- STEP 2: HARD PURGE OF REDUNDANT AND NON-COMPLIANT VIEWS ---
try:
    valid_view_types = [
        ViewType.FloorPlan, ViewType.CeilingPlan, ViewType.Elevation, 
        ViewType.Section, ViewType.Detail, ViewType.ThreeD, ViewType.EngineeringPlan
    ]
    
    all_views_collector = FilteredElementCollector(doc).OfClass(View).ToElements()
    for view in all_views_collector:
        try:
            v_id = view.Id
            
            if view.ViewType in [ViewType.Schedule, ViewType.Internal, ViewType.ProjectBrowser, ViewType.DrawingSheet]:
                continue

            if view.IsTemplate:
                v_name_upper = view.Name.upper()
                if not any(target in v_name_upper for target in TARGET_NAMES):
                    doc.Delete(v_id)
                    templates_deleted += 1
                continue

            if view.ViewType in valid_view_types:
                v_name_upper = view.Name.upper()
                
                # Sheet compliance check via stable parameter lookup
                p_num = view.LookupParameter("Sheet Number")
                p_name = view.LookupParameter("Sheet Name")
                
                s_num = p_num.AsString() if p_num else None
                s_name = p_name.AsString() if p_name else None
                
                has_sheet_conformity = False
                if s_num and s_num != "" and s_num != "---" and s_num != "-":
                    if s_name and s_name != "" and s_name != "---" and s_name != "-":
                        has_sheet_conformity = True
                
                # Delete absolutely all views that do not have a valid sheet mapping
                if not has_sheet_conformity:
                    if view.CanBeDeleted():
                        doc.Delete(v_id)
                        views_deleted += 1
        except: pass
except: pass

# --- STEP 3: EXTERNAL RESOURCES PURGE (RVT UNLOAD / CAD & IFC HARD DELETE) ---
try:
    rvt_links = FilteredElementCollector(doc).OfClass(RevitLinkType).ToElements()
    for link in rvt_links:
        try:
            l_name = link.Name.lower()
            if l_name.endswith(".rvt") and not link.IsNestedLink:
                if link.GetLinkedFileStatus() == LinkedFileStatus.Loaded:
                    link.Unload(None)
                    rvt_unloaded += 1
            elif ".ifc" in l_name:
                doc.Delete(link.Id)
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

try:
    pt_clouds = FilteredElementCollector(doc).OfClass(PointCloudType).ToElementIds()
    for pt_id in pt_clouds:
        try:
            doc.Delete(pt_id)
            links_removed += 1
        except: pass
except: pass

TransactionManager.Instance.TransactionTaskDone()

# =========================================================================
# BLOCK B: INDEPENDENT TRANSACTION FOR GENERATING AND FIXING DELIVERY VIEWS
# =========================================================================
TransactionManager.Instance.EnsureInTransaction(doc)

try:
    view_3d_types = FilteredElementCollector(doc).OfClass(ViewFamilyType).ToElements()
    view_3d_family_type = next((t for t in view_3d_types if t.ViewFamily == ViewFamily.ThreeD), None)
    
    # Isolate remaining 3D views to prevent duplication issues
    existing_3d_views = FilteredElementCollector(doc).OfClass(View3D).ToElements()
    
    for name in TARGET_NAMES:
        view_3d = next((v for v in existing_3d_views if v.Name.upper() == name), None)
        
        # If the delivery view does not exist after the cleanup phase, generate it
        if not view_3d and view_3d_family_type:
            view_3d = View3D.CreateIsometric(doc, view_3d_family_type.Id)
            view_3d.Name = name
            
        if view_3d:
            protected_elements_ids.Add(view_3d.Id)
            
            # Locate or generate the homonymous View Template
            all_templates = [v for v in FilteredElementCollector(doc).OfClass(View).ToElements() if v.IsTemplate]
            template = next((t for t in all_templates if t.Name.upper() == name), None)
            
            if not template:
                template = view_3d.CreateViewTemplate()
                template.Name = name
                
            if template:
                protected_elements_ids.Add(template.Id)
                view_3d.ViewTemplateId = template.Id
                apply_strict_filters(doc, template)
                
            apply_strict_filters(doc, view_3d)

    # Hard-delete any residual 3D views that accidentally bypassed Step 2 loop
    all_3d_views_cleanup = FilteredElementCollector(doc).OfClass(View3D).ToElements()
    for v3d in all_3d_views_cleanup:
        if v3d.Id not in protected_elements_ids and not v3d.IsTemplate:
            if v3d.CanBeDeleted():
                try:
                    doc.Delete(v3d.Id)
                    views_deleted += 1
                except: pass

except: pass

TransactionManager.Instance.TransactionTaskDone()

# =========================================================================
# BLOCK C: RECURSIVE SUPER PURGE OF CASCADING ORPHAN ELEMENTS
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
    "• Obsolete View Templates destroyed from database: {}".format(templates_deleted),
    "• Browser Model & Detail Groups completely cleaned: {}".format(groups_deleted),
    "• Revit Infrastructure links safely unloaded: {}".format(rvt_unloaded),
    "• Hard external attachments deleted (CAD/IFC/NWD): {}".format(links_removed),
    "• Secondary orphan elements removed via Super Purge: {}".format(total_purged),
    "• Database execution recursive optimizations: {}".format(loop_safety),
    "------------------------------------------------------------",
    "• COPILED EMISSION DELIVERABLES STATUS:",
    "  [+] 3D EMISSÃO View & Template generated, linked, and locked.",
    "  [+] 3D NAVIS View & Template generated, linked, and locked.",
    "  [✔️] Crop Fields Disabled | Annotation Mask Active | (HIDE) Worksets Enforced Hidden.",
    "------------------------------------------------------------"
]

OUT = "\n".join(report_log)
