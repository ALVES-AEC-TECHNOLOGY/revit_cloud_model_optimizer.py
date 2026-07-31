import sys
import clr
from Autodesk.Revit.DB import *

clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager

clr.AddReference('System')
from System.Collections.Generic import HashSet

# Initialize document and tracking variables
doc = DocumentManager.Instance.CurrentDBDocument
created_elements_ids = HashSet[ElementId]()
target_names = ["3D EMISSAO", "3D NAVIS"]

views_deleted = 0
groups_deleted = 0
links_rvt_removed = 0
links_ifc_removed = 0
total_purged = 0

# Start transaction in Dynamo context
TransactionManager.Instance.EnsureInTransaction(doc)
try:
    # Step 1: Preserve or Create Target 3D Views
    existing_3d_views = list(FilteredElementCollector(doc).OfClass(View3D).ToElements())
    existing_3d_names = [str(view.Name).upper() for view in existing_3d_views]

    view_3d_types = list(FilteredElementCollector(doc).OfClass(ViewFamilyType).ToElements())
    default_3d_type = next((t for t in view_3d_types if t.ViewFamily == ViewFamily.ThreeD), None)

    # Create target views if they don't exist
    for name in target_names:
        if name not in existing_3d_names and default_3d_type is not None:
            try:
                new_view = View3D.CreateIsometric(doc, default_3d_type.Id)
                new_view.Name = name
                created_elements_ids.Add(new_view.Id)
            except:
                pass

    # Step 2: Delete Unwanted 3D Views
    view_ids_to_delete = [v.Id for v in existing_3d_views if not (str(v.Name).upper() in target_names)]
    for view_id in view_ids_to_delete:
        try:
            view_elem = doc.GetElement(view_id)
            if view_elem is not None and not view_elem.IsTemplate and view_elem.CanBeDeleted():
                doc.Delete(view_id)
                views_deleted += 1
        except:
            pass

    # Step 3: Delete Groups (Instances first, then Types to guarantee deletion)
    group_instances = list(FilteredElementCollector(doc).OfClass(Group).ToElementIds())
    for gi_id in group_instances:
        try:
            doc.Delete(gi_id)
        except:
            pass
    
    group_types = list(FilteredElementCollector(doc).OfClass(GroupType).ToElementIds())
    for gt_id in group_types:
        try:
            doc.Delete(gt_id)
            groups_deleted += 1
        except:
            pass

    # Step 4: Manage Links (RVT Unload)
    rvt_links = list(FilteredElementCollector(doc).OfClass(RevitLinkType).ToElements())
    for link in rvt_links:
        try:
            if not link.IsNestedLink and link.GetLinkedFileStatus() == LinkedFileStatus.Loaded:
                link.Unload(None)
                links_rvt_removed += 1
        except:
            pass

    # Step 5: Delete CAD/DWG and IFC Links (Instances first, then Types)
    cad_instances = list(FilteredElementCollector(doc).OfClass(ImportInstance).ToElementIds())
    for ci_id in cad_instances:
        try:
            doc.Delete(ci_id)
        except:
            pass

    cad_types = list(FilteredElementCollector(doc).OfClass(CADLinkType).ToElementIds())
    for ct_id in cad_types:
        try:
            doc.Delete(ct_id)
            links_ifc_removed += 1
        except:
            pass

    # Crucial step closing general transaction block before launching Purge loop cycles
    TransactionManager.Instance.TransactionTaskDone()

    # Step 6: Deep Super Purge Loop (Revit 2024+ CPython3 Compliant)
    purge_loops = 0
    while purge_loops < 10:
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
                total_purged += 1
                deleted_this_loop += 1
            except:
                pass

        TransactionManager.Instance.TransactionTaskDone()
        if deleted_this_loop == 0:
            break
        purge_loops += 1

    # Finalize reports with deleted counts
    final_report = [
        "🔥 PURGING PROCESS COMPLETED 🔥",
        "-" * 45,
        "• 3D Views Deleted: {}".format(views_deleted),
        "• Group Types Removed from Browser: {}".format(groups_deleted),
        "• Revit Links Unloaded (RVT): {}".format(links_rvt_removed),
        "• Links IFC/CAD Removed: {}".format(links_ifc_removed),
        "• Total Redundant Items Purged: {}".format(total_purged),
        "-" * 45
    ]
    OUT = "\n".join(final_report)

except Exception as ex:
    if TransactionManager.Instance.IsTransactionActive():
        TransactionManager.Instance.TransactionTaskDone()
    final_report = ["❌ FATAL ERROR EXECUTED: {}".format(str(ex))]
    OUT = "\n".join(final_report)

else:
    OUT = "\n".join(final_report)
