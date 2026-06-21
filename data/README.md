# PropellerLab Local Data

This folder is the project-local data library for user-managed PropellerLab files.

Suggested layout:

- `airfoils/`: airfoil coordinate DAT files, imported polar CSV files, and saved XFOIL polar files.
- `blade_geometries/`: propeller blade geometry CSV files.
- `designs/`: Optimization Design geometry exports and design station CSV files.

The folder structure is tracked by Git, but user data placed inside the subfolders is ignored by default. Keep files here when you want them available locally without accidentally pushing large or private design data.
