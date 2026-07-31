import clr
clr.AddReference('RevitAPI')
from Autodesk.Revit.DB import *
import Autodesk

def delete_unused_views(doc):
    collector = FilteredElementCollector(doc)
    views = [e for e in collector.OfClass(View) if not e.IsTemplate and not e.IsPrintingView]

    used_views = set()
    sheets = FilteredElementCollector(doc).OfClass(Sheet).ToElements()

    for sheet in sheets:
        used_views.update(sheet.GetAllPlacedViews())

    for view in views:
        if view.Id not in used_views:
            doc.Delete(view.Id)

def delete_groups(doc):
    collector = FilteredElementCollector(doc)
    groups = [e for e in collector.OfClass(Group)]

    for group in groups:
        doc.Delete(group.Id)

def unload_links(doc):
    collector = FilteredElementCollector(doc).OfClass(RevitLinkType)
    link_types = collector.ToElements()

    for link_type in link_types:
        if not isinstance(link_type, RevitLinkInstance):
            continue

        link_instance = doc.GetElement(link_type.GetTargetId())
        doc.Delete(link_instance.Id)

def super_purge(doc):
    uidoc = Autodesk.Revit.UI.DocumentManager.Instance.CurrentUIDocument
    cmd_data = CommandData()
    command = SuperPurgeCommand(cmd_data)
    command.Execute()

def main():
    doc = __revit__.ActiveUIDocument.Document
    delete_unused_views(doc)
    delete_groups(doc)
    unload_links(doc)
    super_purge(doc)

if __name__ == '__main__':
    main()
