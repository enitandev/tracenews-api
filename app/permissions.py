PERMISSIONS = {
    "corrections": {
        "reader": "no",
        "read_only": "view",
        "tech": "no",
        "editorial": "yes",
        "super_admin": "yes"
    },
    "politicians": {
        "reader": "no",
        "read_only": "view",
        "tech": "no",
        "editorial": "yes",
        "super_admin": "yes"
    },
    "monitoring_spirit": {
        "reader": "no",
        "read_only": "view",
        "tech": "no",
        "editorial": "yes",
        "super_admin": "yes"
    },
    "reports": {
        "reader": "no",
        "read_only": "view",
        "tech": "no",
        "editorial": "yes",
        "super_admin": "yes"
    },
    "platform_health": {
        "reader": "no",
        "read_only": "view",
        "tech": "yes",
        "editorial": "no",
        "super_admin": "yes"
    },
    "audit_ledger": {
        "reader": "no",
        "read_only": "view",
        "tech": "view",
        "editorial": "view",
        "super_admin": "yes"
    },
    "reader_data": {
        "reader": "no",
        "read_only": "no",
        "tech": "no",
        "editorial": "no",
        "super_admin": "yes"
    },
    "staff_management": {
        "reader": "no",
        "read_only": "no",
        "tech": "no",
        "editorial": "no",
        "super_admin": "yes"
    },
    "console_access": {
        "reader": "no",
        "read_only": "yes",
        "tech": "yes",
        "editorial": "yes",
        "super_admin": "yes"
    }
}

def has_permission(role: str, is_staff_fallback: bool, section: str, action: str = "view") -> bool:
    if role is None:
        return bool(is_staff_fallback)
    if role == "reader":
        return False
        
    section_perms = PERMISSIONS.get(section)
    if not section_perms:
        return False
        
    user_perm = section_perms.get(role)
    if not user_perm or user_perm == "no":
        return False
        
    if action == "view":
        return user_perm in ["view", "yes"]
        
    return user_perm == "yes"

def is_staff_role(role: str, is_staff_fallback: bool) -> bool:
    if role is None:
        return bool(is_staff_fallback)
    return role != "reader"
