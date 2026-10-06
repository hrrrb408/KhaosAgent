# Memory Plugin v1

This is the first stateful Khaos Plugin Candidate. Its Manifest requests no
workspace access and no process.exec; the Trusted Launcher can approve and
run it without opening a workspace Picker.

The Candidate supports remember, recall, and forget. It stores one canonical
UTF-8 JSON blob through state.read and state.replace:

    {"format":"khaos-memory-v1","items":{"project_codename":"Project K"}}

The Kernel treats the blob as opaque. The schema belongs to this Plugin. A
replacement Candidate with the same logical id reads the same state. Different
Plugin IDs receive different namespaces. State is not part of the Candidate
package, workspace, or activation metadata.
