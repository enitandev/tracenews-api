from fastapi import APIRouter, HTTPException, Header, Depends
from pydantic import BaseModel, EmailStr
from app.db import supabase

router = APIRouter()


class SignupRequest(BaseModel):
    email: EmailStr
    password: str
    age_assertion: bool  # must be explicitly True — no default, no pre-check

@router.post("/api/auth/signup", status_code=201)
async def signup(payload: SignupRequest):
    if not payload.age_assertion:
        raise HTTPException(
            status_code=400,
            detail="You must confirm you are 18 or older to create an account.",
        )

    try:
        auth_res = supabase.auth.sign_up({
            "email": payload.email,
            "password": payload.password,
        })
        if not auth_res.user:
            raise HTTPException(status_code=400, detail="Signup failed")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    supabase.table("profiles").insert({
        "id": auth_res.user.id,
        "age_assertion": True,
    }).execute()

    return {"id": auth_res.user.id, "email": payload.email, "status": "confirmation_email_sent"}


def get_current_user(authorization: str = Header(...)):
    """Validates the Supabase session token, returns the user id."""
    token = authorization.replace("Bearer ", "")
    user_res = supabase.auth.get_user(token)
    if not user_res or not user_res.user:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    return user_res.user.id


@router.delete("/api/auth/account")
async def delete_account(user_id: str = Depends(get_current_user)):
    """
    Deletes the auth.users row. profiles cascades automatically (ON DELETE
    CASCADE). Once the reader-analytics feature ships, its counters table
    must ALSO cascade from this same deletion — confirm that when it's built,
    don't assume it silently works.
    """
    supabase.auth.admin.delete_user(user_id)
    return {"status": "deleted"}
