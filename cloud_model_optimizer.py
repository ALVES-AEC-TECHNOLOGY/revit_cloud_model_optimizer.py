# -*- coding: utf-8 -*-
"""
Script de Limpeza de Modelo, Auditoria e Emissão BIM
Autor: ALVES AEC TECHNOLOGY
Descrição: Script corrigido de ponta a ponta para execução no IronPython do Dynamo.
"""

import sys
import clr

# Importar Elementos da API do Revit
clr.AddReference('RevitAPI')
from Autodesk.Revit.DB import *

# Importar Serviços de Transação e Documento do Dynamo (Nome corrigido: Persistence)
clr.AddReference('RevitServices')
import RevitServices
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager

# Importar Coleções do .NET System
clr.AddReference('System')
import System
from System.Collections.Generic import HashSet

# INICIALIZAÇÃO DE VARIÁVEIS DO DOCUMENTO
doc = DocumentManager.Instance.CurrentDBDocument
createdElementsIds = HashSet[ElementId]()
targetNames = ["3D EMISSAO", "3D NAVIS"]
viewCache = {}

# Inicialização correta de todos os contadores para evitar NameError
views_deleted = 0
groupsDeleted = 0
linksRvtRemoved = 0
linksIfcRemoved = 0
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
