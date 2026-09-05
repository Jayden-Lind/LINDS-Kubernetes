ImageUpdater resources for Applications that are parked in
`applications/disabled/`. The argocd-image-updater Application syncs
`image-updates/` without recursion, so nothing in here is applied.

An ImageUpdater whose `applicationRefs` name an Application that does not exist
never finishes its reconcile, and the controller's readiness "warmup" check
stays failed for as long as one such resource exists. Move the file back up one
level when the matching Application is re-enabled.
