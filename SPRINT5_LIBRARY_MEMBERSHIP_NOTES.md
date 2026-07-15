# Sprint 5 — Library Membership

## Behaviour

- **Browse Folder** opens a directory temporarily and reads metadata for the current view without adding new records to the persistent library index.
- **Add Folder to Library** explicitly registers a folder and reloads it so its images are indexed.
- **All Images** and **Smart Collections** include only indexed files located beneath registered library folders.
- Removing a folder from the library never deletes files. Existing index rows are ignored once the folder is unregistered.

## Manual checks

1. Browse an unregistered folder and confirm the toolbar says `Browsing` and the status shows `Browse mode` after metadata finishes.
2. Confirm its images do not appear in **Library → All Images** or a Smart Collection.
3. Add that folder using **File → Add Folder to Library…**.
4. Wait for indexing to complete and confirm its images appear in **All Images** and matching Smart Collections.
5. Remove the folder using **Manage Library Folders…** and confirm its files remain on disk and disappear from library-wide views.
