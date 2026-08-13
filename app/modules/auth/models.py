from sqlalchemy import Column, String, ForeignKey, Table
from sqlalchemy.orm import relationship
from app.core.database import Base

# Association table for Role-Permission (Many-to-Many)
role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column("role_id", String(50), ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column("permission_id", String(50), ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True)
)

class Role(Base):
    __tablename__ = "roles"

    id = Column(String(50), primary_key=True)
    name = Column(String(50), nullable=False, unique=True)

    permissions = relationship("Permission", secondary=role_permissions, back_populates="roles")

class Permission(Base):
    __tablename__ = "permissions"

    id = Column(String(50), primary_key=True)
    description = Column(String(255), nullable=True)

    roles = relationship("Role", secondary=role_permissions, back_populates="permissions")

class UserRole(Base):
    __tablename__ = "user_roles"

    user_id = Column(String(255), primary_key=True)  # Supabase Auth ID
    role_id = Column(String(50), ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True)
