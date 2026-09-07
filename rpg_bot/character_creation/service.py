"""Application boundary between completed creation flows and persistence."""

from ..database import Database
from ..models import Character
from .models import CharacterCreationResult


class CharacterCreationService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def persist(
        self, discord_user_id: int, result: CharacterCreationResult
    ) -> Character:
        # Vitality owns starting HP in the source rules. Keeping the mapping here
        # prevents persistence concerns from leaking into the creation flow.
        max_hp = result.final_attributes["Vitality"]
        return self.database.create_character(
            discord_user_id,
            result.name,
            max_hp,
            lineage=result.lineage,
            race=result.race,
            age=result.age,
            gender=result.gender,
            attributes=result.final_attributes,
            skills=result.skill_ranks,
        )
