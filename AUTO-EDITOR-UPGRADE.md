# Upgrade an existing Clyp installation

This upgrade keeps your existing SQLite database, accounts, uploads and exports.

1. Stop the running PHP server with `Ctrl + C`.
2. Extract the upgrade ZIP.
3. Copy its contents into the existing Clyp folder.
4. Select **Replace files in the destination**.
5. Do not delete `storage/clyp.sqlite`, `storage/uploads` or `storage/exports`.
6. Run:

```powershell
cd C:\Users\adyem\Desktop\clyp
php .\scripts\install.php
php .\scripts\check.php
.\start.bat
```

The schema installer adds the one-click editing columns automatically.

For an existing project, open it, regenerate or review the captions, open **Auto edit**, and click **Create one-click edit** before rendering.
