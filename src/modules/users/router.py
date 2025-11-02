# src/modules/users/router.py
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from core.database import get_db # <-- 导入 get_db
from shared.models import users  # 导入你的模型

router = APIRouter()

@router.get("/{user_id}")
def read_user(user_id: int, db: Session = Depends(get_db)): # <-- 使用依赖注入
    user = db.query(users.User).filter(users.User.id == user_id).first()
    return user