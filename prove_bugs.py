"""Prove the 3 bugs that existed in the original skill script v1.1.0."""

def encode_path_original_windows(p):
    # From skill v1.1.0 — only replaces : \ /
    return p.replace(':', '-').replace('\\', '-').replace('/', '-')

def encode_path_original_unix(p):
    # From skill v1.1.0 — only replaces /
    return p.replace('/', '-')

print("=" * 60)
print("BUG 1 — encode_path: Windows space not converted")
result   = encode_path_original_windows(r'C:\Users\Yoda\Downloads\Claude Code')
expected = 'C--Users-Yoda-Downloads-Claude-Code'
print(f"  original -> '{result}'")
print(f"  expected    '{expected}'")
print(f"  BUG={result != expected}\n")

print("BUG 2 — encode_path: Unix hidden dir (/.name) not double-dashed")
result   = encode_path_original_unix('/Users/martin/.config/myproject')
expected = '-Users-martin--config-myproject'
print(f"  original -> '{result}'")
print(f"  expected    '{expected}'")
print(f"  BUG={result != expected}\n")

print("BUG 3 — cwd field: substring 'in' check causes prefix collision")
old = '/Users/you/proj'
cwd_colliding = '/Users/you/proj-backup'
would_patch_original = old in cwd_colliding   # original logic: substring match
would_patch_fixed    = cwd_colliding == old   # fixed logic: exact match
print(f"  OLD='{old}', cwd='{cwd_colliding}'")
print(f"  Original (substring 'in'): patches={would_patch_original}  <- BUG (false positive)")
print(f"  Fixed    (exact '=='):      patches={would_patch_fixed}  <- correct")
