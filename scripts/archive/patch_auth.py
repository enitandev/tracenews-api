import re
with open("app/routers/auth.py", "r") as f:
    code = f.read()

old_code = """    token = authorization.replace("Bearer ", "")
    user_res = supabase.auth.get_user(token)
    if not user_res or not user_res.user:
        raise HTTPException(status_code=401, detail="Invalid or expired session")"""

new_code = """    token = authorization.replace("Bearer ", "")
    import gotrue.errors
    try:
        user_res = supabase.auth.get_user(token)
    except gotrue.errors.AuthApiError:
        raise HTTPException(status_code=401, detail="Invalid token")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")
        
    if not user_res or not user_res.user:
        raise HTTPException(status_code=401, detail="Invalid or expired session")"""

code = code.replace(old_code, new_code)
with open("app/routers/auth.py", "w") as f:
    f.write(code)
print("Patched auth.py")
