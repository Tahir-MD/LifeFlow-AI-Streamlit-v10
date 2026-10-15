from fastapi import APIRouter, Depends
from app.models.receiver import Receiver
from app.schemas.receiver_schema import ReceiverOut
from app.utils.dependencies import get_current_receiver

router = APIRouter(prefix="/receivers", tags=["Receivers"])


@router.get("/me", response_model=ReceiverOut)
def read_my_receiver_profile(current_receiver: Receiver = Depends(get_current_receiver)):
    return current_receiver
