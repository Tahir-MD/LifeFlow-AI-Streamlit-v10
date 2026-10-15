from pydantic import BaseModel


class PushSubscribeIn(BaseModel):
    endpoint: str
    p256dh_key: str
    auth_key: str


class PushUnsubscribeIn(BaseModel):
    endpoint: str


class PushStatusOut(BaseModel):
    configured: bool
    public_key: str = ""
