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

# Reporting counters
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
        # Configuração de CropBox
        view_or_template.CropBoxActive = False
        view_or_template.CropBoxVisible = False
        
        # Desabilitar Annotations com segurança (funciona em Views e Templates)
        if view_or_template.IsTemplate:
            # Garante que a categoria de anotação (V/G Overrides Annotation) seja controlada pelo template
            # Parâmetro interno do Revit correspondente à visibilidade de anotações
            v_g_annotation_param_id = ElementId(BuiltInParameter.VIEW_TEMPLATE_SETTINGS) 
            # Em muitas versões do Revit, usa-se a negação de categorias ocultas:
            view_or_template.AreAnnotationCategoriesHidden = True
        else:
            view_or_template.AreAnnotationCategoriesHidden = True
        
        # Ocultar Worksets com "(HIDE)" no nome
        if document.IsWorkshared:
            worksets_collector = FilteredWorksetCollector(document).OfKind(WorksetKind.UserWorkset)
            for wk in worksets_collector:
                if "(HIDE)" in wk.Name.upper():
                    view_or_template.SetWorksetVisibility(wk.Id, WorksetVisibility.Hidden)
    except: 
        pass

# =========================================================================
# OPERAÇÃO ANTECIPADA: CRIAR AS VISTAS ALVO PARA GARANTIR VISTA ATIVA
# =========================================================================
# (Corrigindo o problema do Revit travar ao deletar a vista ativa do usuário)
TransactionManager.Instance.EnsureInTransaction(doc)
try:
    view_3d_types = FilteredElementCollector(doc).OfClass(ViewFamilyType).ToElements()
    view_3d_family_type = next((t for t in view_3d_types if t.ViewFamily == ViewFamily.ThreeD), None)
    
    existing_3d_views = FilteredElementCollector(doc).OfClass(View3D).ToElements()
    
    for name in TARGET_NAMES:
        view_3d = next((v for v in existing_3d_views if v.Name.upper() == name), None)
        
        # Se não existir, cria a vista 3D obrigatória antes da limpeza
        if not view_3d and view_3d_family_type:
            view_3d = View3D.CreateIsometric(doc, view_3d_family_type.Id)
            view_3d.Name = name
        
        if view_3d:
            created_elements_ids.Add(view_3d.Id)
except: 
    pass
TransactionManager.Instance.TransactionTaskDone()


# =========================================================================
# PHASE 1: STATIC VIEW & GROUP CLEANUP (CORRIGIDO)
# =========================================================================
view_ids = FilteredElementCollector(doc).OfClass(View).ToElementIds()

TransactionManager.Instance.EnsureInTransaction(doc)

for v_id in view_ids:
    try:
        view = doc.GetElement(v_id)
        if view is None:
            continue
            
        # Ignorar vistas internas do sistema
        if view.ViewType in [ViewType.Schedule, ViewType.Internal, ViewType.ProjectBrowser, ViewType.DrawingSheet]:
            continue
            
        # CORREÇÃO: Preservar TODOS os View Templates existentes do projeto
        if view.IsTemplate:
            continue 

        valid_view_types = [
            ViewType.FloorPlan, ViewType.CeilingPlan, ViewType.Elevation, 
            ViewType.Section, ViewType.Detail, ViewType.ThreeD, ViewType.EngineeringPlan
        ]
        
        if view.ViewType in valid_view_types:
            v_name_upper = view.Name.upper()
            
            # Proteger as vistas recém-criadas/alvo
            if v_name_upper in TARGET_NAMES:
                continue 
                
            # CORREÇÃO: Discriminar vistas em folhas usando SheetId (Propriedade Nativa)
            is_on_sheet = view.SheetId != ElementId.InvalidElementId
            
            # Se for uma vista 3D qualquer (que não as alvo) OU não estiver em folha, deleta
            if view.ViewType == ViewType.ThreeD or not is_on_sheet:
                if view.CanBeDeleted() and v_id not in created_elements_ids:
                    doc.Delete(v_id)
                    views_deleted += 1
                    
    except: 
        pass

# Deletar os GroupTypes do modelo
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
# PHASE 2: STATIC MANAGE LINKS CLEANUP
# =========================================================================
TransactionManager.Instance.EnsureInTransaction(doc)

link_ids = FilteredElementCollector(doc).OfClass(RevitLinkType).ToElementIds()

for l_id in link_ids:
    try:
        link = doc.GetElement(l_id)
        if link is None:
            continue
            
        link_name = Element.Name.GetValue(link).lower()
        
        if link_name.endswith(".rvt") and not link.IsNestedLink:
            if link.GetLinkedFileStatus() == LinkedFileStatus.Loaded:
                link.Unload(None)
                rvt_unloaded += 1
        elif ".ifc" in link_name:
            doc.Delete(l_id)
            links_removed += 1
    except: pass

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
# PHASE 3: CONFIGURE TARGET DELIVERY VIEWS & GENERATE TEMPLATES
# =========================================================================
TransactionManager.Instance.EnsureInTransaction(doc)
try:
    existing_3d_views = FilteredElementCollector(doc).OfClass(View3D).ToElements()
    all_templates = [v for v in FilteredElementCollector(doc).OfClass(View).ToElements() if v.IsTemplate]
    
    for name in TARGET_NAMES:
        view_3d = next((v for v in existing_3d_views if v.Name.upper() == name), None)
        
        if view_3d:
            # Buscar se já existe um View Template com o mesmo nome exato
            template = next((t for t in all_templates if t.Name.upper() == name), None)
            
            # Se não existir o View Template, cria a partir da vista 3D alvo
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
            total_purged += 1
            purged_this_loop += 1
        except: pass
        
    TransactionManager.Instance.TransactionTaskDone()
    if purged_this_loop == 0:
        break
    loop_safety += 1

# OUTPUT LOG PARA O DYNAMO
OUT = "Limpeza Concluída: Vistas Deletadas: {}, Grupos: {}, Links/CADs Removidos: {}, Elementos Purgados: {}".format(views_deleted, groups_deleted, links_removed, total_purged)
totalPurged = 0

# =========================================================================
# PHASE 0: PREPARE FOR PURGING & TARGET VIEW CREATION
# =========================================================================
TransactionManager.Instance.EnsureInTransaction(doc)
try:
    # Coleta o tipo de família 3D padrão do projeto de forma segura
    view_3d_types = FilteredElementCollector(doc).OfClass(ViewFamilyType).ToElements()
    view_3d_family_type = next((t for t in view_3d_types if t.ViewFamily == ViewFamily.ThreeD), None)
    
    existing_3d_views = FilteredElementCollector(doc).OfClass(View3D).ToElements()

    for name in targetNames:
        # Verifica se a vista já existe no modelo
        view_3d = next((v for v in existing_3d_views if v.Name.upper() == name.upper()), None)
        
        # Se não existir, cria a vista 3D isométrica usando o tipo correto
        if not view_3d and view_3d_family_type:
            view_3d = View3D.CreateIsometric(doc, view_3d_family_type.Id)
            view_3d.Name = name
        
        if view_3d:
            createdElementsIds.Add(view_3d.Id)
            viewCache[name] = view_3d.Id
except:
    pass
TransactionManager.Instance.TransactionTaskDone()

# =========================================================================
# PURGE PHASE 1: UNLOAD LINKED FILES (RVT) AND CAD LINKS
# =========================================================================
TransactionManager.Instance.EnsureInTransaction(doc)

linkIds = FilteredElementCollector(doc).OfClass(RevitLinkType).ToElementIds()
for linkId in linkIds:
    try:
        element = doc.GetElement(linkId)
        if not element:
            continue

        linkName = Element.Name.GetValue(element).lower()
        
        # Descarrega arquivos RVT
        if linkName.endswith(".rvt") and not element.IsNestedLink:
            if element.GetLinkedFileStatus() == LinkedFileStatus.Loaded:
                element.Unload(None)
                linksRvtRemoved += 1
        # Deleta arquivos IFC vinculados
        elif ".ifc" in linkName:
            doc.Delete(linkId)
            linksIfcRemoved += 1
    except:
        pass

# Remoção de categorias de CAD, Nuvem de Pontos e Modelos de Coordenação
linkCategories = [CADLinkType, PointCloudType, CoordinationModelType, TopographyLinkType]
for cat in linkCategories:
    try:
        catIds = FilteredElementCollector(doc).OfClass(cat).ToElementIds()
        for c_id in catIds:
            try:
                doc.Delete(c_id)
                linksIfcRemoved += 1
            except:
                pass
    except:
        pass

try:
    importInstances = FilteredElementCollector(doc).OfClass(ImportInstance).ToElementIds()
    for inst_id in importInstances:
        try:
            doc.Delete(inst_id)
            linksIfcRemoved += 1
        except:
            pass
except:
    pass

TransactionManager.Instance.TransactionTaskDone()

# =========================================================================
# PURGE PHASE 2: REMOVE GROUPS
# =========================================================================
TransactionManager.Instance.EnsureInTransaction(doc)
try:
    groupIds = FilteredElementCollector(doc).OfClass(GroupType).ToElementIds()
    for groupId in groupIds:
        try:
            doc.Delete(groupId)
            groupsDeleted += 1
        except:
            pass
except:
    pass
TransactionManager.Instance.TransactionTaskDone()

# =========================================================================
# PURGE PHASE 3: REMOVE UNWANTED VIEWS
# =========================================================================
TransactionManager.Instance.EnsureInTransaction(doc)

viewIds = FilteredElementCollector(doc).OfClass(View).ToElementIds()
for viewId in viewIds:
    try:
        element = doc.GetElement(viewId)
        if not element:
            continue
            
        # Ignorar schedules, folhas e templates existentes na varredura
        if element.ViewType in [ViewType.Schedule, ViewType.Internal, ViewType.ProjectBrowser, ViewType.DrawingSheet]:
            continue
        if element.IsTemplate:
            continue

        # Filtrar apenas tipos de vistas elegíveis para deleção (incluindo 3D antigos)
        validViewTypes = [
            ViewType.FloorPlan, ViewType.CeilingPlan, ViewType.Elevation,
            ViewType.Section, ViewType.Detail, ViewType.ThreeD, ViewType.EngineeringPlan
        ]
        
        if element.ViewType not in validViewTypes:
            continue

        # Proteger as vistas alvo recém-criadas
        if element.Name.upper() in targetNames:
            continue

        # Checar se a vista está associada a alguma folha de prancha
        isOnSheet = element.SheetId != ElementId.InvalidElementId

        # Se for um 3D genérico ou não estiver em folha, remove do modelo
        if element.ViewType == ViewType.ThreeD or not isOnSheet:
            if element.CanBeDeleted() and viewId not in createdElementsIds:
                doc.Delete(viewId)
                views_deleted += 1
    except:
        pass

TransactionManager.Instance.TransactionTaskDone()

# =========================================================================
# PURGE PHASE 4: CREATE/ASSOCIATE TARGET TEMPLATES
# =========================================================================
TransactionManager.Instance.EnsureInTransaction(doc)
try:
    existing_3d_views = FilteredElementCollector(doc).OfClass(View3D).ToElements()
    allTemplates = [v for v in FilteredElementCollector(doc).OfClass(View).ToElements() if v.IsTemplate]
    
    for name in targetNames:
        view_3d = next((v for v in existing_3d_views if v.Name.upper() == name.upper()), None)
        
        if view_3d:
            # Procura se o View Template com o mesmo nome já existe
            template = next((t for t in allTemplates if t.Name.upper() == name.upper()), None)
            
            # Se não existir, cria o View Template usando a vista 3D como matriz
            if not template:
                template = view_3d.CreateViewTemplate()
                template.Name = name
                
            if template:
                createdElementsIds.Add(template.Id)
                view_3d.ViewTemplateId = template.Id
                
                # Aplica as limpezas de CropBox e Anotações direto no template corporativo
                template.CropBoxActive = False
                template.CropBoxVisible = False
                template.AreAnnotationCategoriesHidden = True
except:
    pass
TransactionManager.Instance.TransactionTaskDone()

# =========================================================================
# PURGE PHASE 5: RECURSIVE PURGE OF UNUSED ELEMENTS (DATABASE CLEANUP)
# =========================================================================
maxPurgeLoops = 10
loopSafety = 0

while loopSafety < maxPurgeLoops:
    TransactionManager.Instance.EnsureInTransaction(doc)
    purgedThisLoop = 0
    try:
        unusedElements = doc.GetUnusedElements(System.Collections.Generic.HashSet[ElementId]())
        if not unusedElements or unusedElements.Count == 0:
            TransactionManager.Instance.TransactionTaskDone()
            break
        
        for eId in unusedElements:
            try:
                doc.Delete(eId)
                totalPurged += 1
                purgedThisLoop += 1
            except:
                pass
    except:
        TransactionManager.Instance.TransactionTaskDone()
        break
        
    TransactionManager.Instance.TransactionTaskDone()
    if purgedThisLoop == 0:
        break
    loopSafety += 1

# RETORNO DE LOGS FORMATADOS PARA O DYNAMO
OUT = "Vistas Deletadas: {}, Grupos Removidos: {}, Links RVT: {}, Links IFC/CAD: {}, Itens Purgados: {}".format(
    views_deleted, groupsDeleted, linksRvtRemoved, linksIfcRemoved, totalPurged
)
