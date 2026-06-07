from fastapi import APIRouter, HTTPException
from app.models import Persona, CreatePersonaRequest
from app import store

router = APIRouter()


@router.post("", response_model=Persona, status_code=201)
async def create_persona(body: CreatePersonaRequest):
    persona = Persona(
        name=body.name,
        relationship_type=body.relationship_type,
        personality_traits=body.personality_traits,
        backstory=body.backstory,
        custom_relationship=body.custom_relationship,
        voice_id=body.voice_id,
        nsfw_mode=body.nsfw_mode,
    )
    return store.create_persona(persona)


@router.get("", response_model=list[Persona])
async def list_personas():
    return store.list_personas()


@router.get("/{persona_id}", response_model=Persona)
async def get_persona(persona_id: str):
    persona = store.get_persona(persona_id)
    if not persona:
        raise HTTPException(status_code=404, detail="Persona not found")
    return persona


@router.delete("/{persona_id}", status_code=204)
async def delete_persona(persona_id: str):
    if not store.delete_persona(persona_id):
        raise HTTPException(status_code=404, detail="Persona not found")
