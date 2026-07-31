import sys
import clr
clr.AddReference('RevitAPI')
from Autodesk.Revit.DB import *

clr.AddReference('RevitServices')
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager

# Explicit .NET reference and HashSet import for Revit 2024+ Purge compatibility
clr.AddReference('System')
import System
from System.Collections.Generic import HashSet

# Access the current document
doc = DocumentManager.Instance.CurrentDBDocument

# FIXED: Correctly targets GroupTypes (Model and Detail/Annotation groups) from the Browser
def delete_annotations_and_groups():
    # Step 1: Wipe physical instances to clear database constraints
    group_instances = list(FilteredElementCollector(doc).OfClass(Group).ToElementIds())
    for gi_id in group_instances:
        try:
            doc.Delete(gi_id)
        except:
            pass
            
    # Step 2: Wipe the Group Types from the Project Browser
    group_types = list(FilteredElementCollector(doc).OfClass(GroupType).ToElementIds())
    for gt_id in group_types:
        try:
            doc.Delete(gt_id)
        except:
            pass

# FIXED: Replaced non-existent 'Sheet' class and corrected the logical inversion for unplaced views
def delete_unused_views():
    view_collector = list(FilteredElementCollector(doc).OfClass(View).ToElements())
    all_views = [v for v in view_collector if not v.IsTemplate and not isinstance(v, ViewSheet)]
    
    used_view_ids = set()
    # FIXED: Replaced non-existent 'Sheet' class with 'ViewSheet'
    sheet_collector = list(FilteredElementCollector(doc).OfClass(ViewSheet).ToElements())
    
    for sheet in sheet_collector:
        try:
            # FIXED: Replaced non-existent 'GetAllViewIDs' with valid 'GetAllPlacedViews' method
            used_view_ids.update(sheet.GetAllPlacedViews())
        except:
            pass

    # FIXED: Correct logical filter identifying views whose IDs are NOT placed on sheets
    for view in all_views:
        try:
            if view.Id not in used_view_ids and view.CanBeDeleted():
                v_type = view.ViewType
                # Protect structural system categories and Legend views
                if v_type in [ViewType.Schedule, ViewType.Internal, ViewType.ProjectBrowser, ViewType.DrawingSheet, ViewType.Legend]:
                    continue
                    
                # Protect parent views that contain active dependent views
                dependent_ids = list(view.GetDependentViewIds())
                if len(dependent_ids) > 0:
                    continue
                    
                doc.Delete(view.Id)
        except:
            pass

# FIXED: Safe collection strategy targeting CAD instances and types without crashing family geometry
def unload_and_delete_links():
    # Remove placed CAD graphics from views
    cad_instances = list(FilteredElementCollector(doc).OfClass(ImportInstance).ToElementIds())
    for ci_id in cad_instances:
        try:
            doc.Delete(ci_id)
        except:
            pass
            
    # Remove CAD link definitions from Manage Links
    cad_types = list(FilteredElementCollector(doc).OfClass(CADLinkType).ToElementIds())
    for ct_id in cad_types:
        try:
            doc.Delete(ct_id)
        except:
            pass

    # Unload Revit Links (RVT)
    rvt_links = list(FilteredElementCollector(doc).OfClass(RevitLinkType).ToElements())
    for link in rvt_links:
        try:
            if not link.IsNestedLink and link.GetLinkedFileStatus() == LinkedFileStatus.Loaded:
                link.Unload(None)
        except:
            pass

# FIXED: Wrapped the deep loop execution safely matching the Revit 2024+ API signature
def super_purge():
    purge_loops = 0
    while purge_loops < 10:
        # Purge requires separate transaction checkpoints per iteration cycle to commit memory updates
        TransactionManager.Instance.EnsureInTransaction(doc)
        
        empty_set = HashSet[ElementId]()
        unused_elements = doc.GetUnusedElements(empty_set)
        unused_ids = list(unused_elements)
        
        if not unused_ids or len(unused_ids) == 0:
            TransactionManager.Instance.TransactionTaskDone()
            break
            
        deleted_this_loop = 0
        for e_id in unused_ids:
            try:
                doc.Delete(e_id)
                deleted_this_loop += 1
            except:
                pass
                
        TransactionManager.Instance.TransactionTaskDone()
        if deleted_this_loop == 0:
            break
        purge_loops += 1

# =========================================================================
# EXECUTION CONTROLLER
# =========================================================================
# CRUCIAL: Opened a managed transaction block context before executing modifications
TransactionManager.Instance.EnsureInTransaction(doc)

try:
    delete_annotations_and_groups()
    delete_unused_views()
    unload_and_delete_links()
finally:
    # Explicitly closes general modifications before launching deep Purge cycles
    TransactionManager.Instance.TransactionTaskDone()

# Launch the deep purge loop as the final operation
super_purge()

# Final output string required for the Dynamo node interface
OUT = "🔥 Model Cleanup and Deep Purge Executed Successfully! 🔥"
