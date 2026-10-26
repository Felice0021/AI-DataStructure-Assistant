"""Purpose-specific outbound permission and text-free append-only audit records."""
from datetime import datetime
from uuid import UUID
from sqlalchemy import CheckConstraint,DateTime,ForeignKey,String,Uuid,UniqueConstraint,Index,func,text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped,mapped_column
from backend.v2.db.base import Base


class CloudConsent(Base):
    __tablename__='cloud_consents'
    __table_args__=(UniqueConstraint('user_id','knowledge_base_id','purpose','service_key'),
        CheckConstraint("purpose IN ('embedding','reranking','generation')",name='purpose'),
        CheckConstraint("provider = 'dashscope'",name='provider'))
    id:Mapped[UUID]=mapped_column(Uuid,primary_key=True,server_default=text('gen_random_uuid()'))
    user_id:Mapped[UUID]=mapped_column(ForeignKey('users.id',ondelete='RESTRICT'))
    knowledge_base_id:Mapped[UUID]=mapped_column(ForeignKey('knowledge_bases.id',ondelete='RESTRICT'))
    purpose:Mapped[str]=mapped_column(String(16))
    provider:Mapped[str]=mapped_column(String(16),server_default='dashscope')
    model:Mapped[str]=mapped_column(String(128))
    service_key:Mapped[str]=mapped_column(String(64))
    granted_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now())
    revoked_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))


class CloudAudit(Base):
    __tablename__='cloud_audits'
    __table_args__=(CheckConstraint("event IN ('granted','revoked','attempt','succeeded','failed')",name='event'),
        Index('ix_cloud_audits_user_created','user_id','created_at'))
    id:Mapped[UUID]=mapped_column(Uuid,primary_key=True,server_default=text('gen_random_uuid()'))
    user_id:Mapped[UUID]=mapped_column(ForeignKey('users.id',ondelete='RESTRICT'))
    purpose:Mapped[str]=mapped_column(String(16))
    service_key:Mapped[str]=mapped_column(String(64))
    event:Mapped[str]=mapped_column(String(16))
    details:Mapped[dict]=mapped_column(JSONB)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now())
