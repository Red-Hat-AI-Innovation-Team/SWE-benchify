#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/libpod/sqlite_state.go b/libpod/sqlite_state.go
index d294ab85b3d..42d31147225 100644
--- a/libpod/sqlite_state.go
+++ b/libpod/sqlite_state.go
@@ -1992,7 +1992,7 @@ func (s *SQLiteState) RemoveVolume(volume *Volume) (defErr error) {
 	}
 	defer func() {
 		if defErr != nil {
-			if err := tx.Rollback(); err != nil {
+			if err = tx.Rollback(); err != nil {
 				logrus.Errorf("Rolling back transaction to remove volume %s: %v", volume.Name(), err)
 			}
 		}
@@ -2007,26 +2007,32 @@ func (s *SQLiteState) RemoveVolume(volume *Volume) (defErr error) {
 	var ctrs []string
 	for rows.Next() {
 		var ctr string
-		if err := rows.Scan(&ctr); err != nil {
+		if err = rows.Scan(&ctr); err != nil {
 			return fmt.Errorf("error scanning row for containers using volume %s: %w", volume.Name(), err)
 		}
 		ctrs = append(ctrs, ctr)
 	}
-	if err := rows.Err(); err != nil {
+	if err = rows.Err(); err != nil {
 		return err
 	}
 	if len(ctrs) > 0 {
 		return fmt.Errorf("volume %s is in use by containers %s: %w", volume.Name(), strings.Join(ctrs, ","), define.ErrVolumeBeingUsed)
 	}
 
-	// TODO TODO TODO:
-	// Need to verify that at least 1 row was deleted from VolumeConfig.
-	// Otherwise return ErrNoSuchVolume
-
-	if _, err := tx.Exec("DELETE FROM VolumeConfig WHERE Name=?;", volume.Name()); err != nil {
+	result, err := tx.Exec("DELETE FROM VolumeConfig WHERE Name=?;", volume.Name())
+	if err != nil {
 		return fmt.Errorf("removing volume %s config from DB: %w", volume.Name(), err)
 	}
 
+	rowsAffected, err := result.RowsAffected()
+	if err != nil {
+		return fmt.Errorf("getting rows affected for volume %q remove: %w", volume.Name(), err)
+	}
+
+	if rowsAffected == 0 {
+		return fmt.Errorf("no volume with name %q found in DB: %w", volume.Name(), define.ErrNoSuchVolume)
+	}
+
 	if _, err := tx.Exec("DELETE FROM VolumeState WHERE Name=?;", volume.Name()); err != nil {
 		return fmt.Errorf("removing volume %s state from DB: %w", volume.Name(), err)
 	}
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
