# Revit Model Purging & Cleanup Automation Script

A production-ready Python automation script designed for **Autodesk Revit 2024+** running the modern **CPython3 engine** inside Dynamo. This script automates model maintenance, data auditing, and file optimization according to strict BIM quality standards.

## 🚀 Key Features

*   **Group Cleanup:** Automatically deletes all active model/detail group instances and removes obsolete Group Types from the Project Browser.
*   **Unplaced View Deletion:** Mapped database filters scan for all 2D views (Plans, Sections, Elevations) that are not placed on any active sheet (`ViewSheet`) and deletes them. 
    *   *Safe-guard:* Automatically protects Parent Views with active dependent views and retains Legend views.
    *   *Note:* 3D Views are skipped by design for manual auditing.
*   **Link & Import Management:** Wipes imported/linked CAD graphics (`ImportInstance`) from all views and drops unused vector layouts (`CADLinkType`) from the Manage Links catalog. Unloads external Revit Links (RVT) while preserving file paths.
*   **Deep Super Purge Loop:** Runs a native recursive 10-cycle loop invoking `GetUnusedElements()` via explicit .NET collections to eliminate complex cascading data blocks.

## 🛠️ Tech Stack & Requirements

*   **Host Environment:** Autodesk Revit 2024 / 2025 / 2026
*   **Visual Programming Context:** Dynamo Sandbox / Dynamo for Revit
*   **Execution Engine:** CPython 3
*   **API Target:** Revit API (`Autodesk.Revit.DB`)

## 📦 Architecture & Design Patterns

The script incorporates advanced Revit API handling routines required to prevent runtime exceptions under the CPython3 framework:
1.  **Static Evaluation:** Avoids runtime database mutation errors by evaluating `FilteredElementCollector` outputs into static native Python lists before loop execution.
2.  **Explicit Typed Collections:** Instantiates memory-compliant C# `HashSet[ElementId]()` arrays via `.NET` system references to fulfill the strict signature requirement of `doc.GetUnusedElements()`.
3.  **Advanced Transaction Handling:** Segregates cleanup phases from the purge loop, ensuring sequential transaction management via `TransactionManager` to maintain model database stability.

## 💻 Installation & Usage

1.  Open your active Revit Model on a Windows x86 machine.
2.  Launch **Dynamo** (`Manage` tab > `Visual Programming` panel > `Dynamo`).
3.  Add a new **Python Script** node to the canvas.
4.  Right-click the node, change the engine setting to **CPython3**.
5.  Double-click the node, delete any default boilerplate text, and paste the code from `revit_cleanup.py`.
6.  Set the Dynamo execution mode to **Manual** (bottom-left corner) and click **Run**.

## 📝 Script Configuration

If you want to manually update the protected categories or safe view filters, navigate to the `delete_unused_views` function parameters:

```python
# Modifying view protections inside the loop
if v_type in [ViewType.Schedule, ViewType.Internal, ViewType.ProjectBrowser, ViewType.DrawingSheet, ViewType.Legend]:
    continue
```

## ⚖️ License

This project is licensed under the MIT License - see the LICENSE file for details.

---
*Disclaimer: Always run this tool in a detached local copy or take a backup of your central model before processing deep purging operations.*
