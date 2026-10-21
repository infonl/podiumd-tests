"""Keycloak test users of bootstrap, and the roles they need that the realm lacks."""

from __future__ import annotations

import json

from dataclasses import dataclass
from dataclasses import field
from typing import TYPE_CHECKING
from typing import cast

from podiumd_tests.auth.keycloak_admin import for_environment
from podiumd_tests.bootstrap.names import PREFIX
from podiumd_tests.json_data import section

if TYPE_CHECKING:
    from podiumd_tests.auth.keycloak_admin import KeycloakAdmin
    from podiumd_tests.bootstrap import Context


def keycloak_password_key(key: str) -> str:
    """Key of a test user's password in the credentials Secret."""
    return f"{PREFIX.replace('-', '_')}_{key}_password"


@dataclass(frozen=True)
class KeycloakUser:
    """Test user ptest-bootstrap-<key> with a random password, and the wanted roles the realm has.

    Admin calls go through auth.keycloak_admin.for_environment.
    """

    key: str
    realm_roles: tuple[str, ...] = ()
    client_roles: tuple[tuple[str, str], ...] = ()
    groups: tuple[str, ...] = ()
    attributes: dict[str, list[str]] = field(default_factory=dict[str, list[str]])
    requires: tuple[str, ...] = ("keycloak",)
    wiring: bool = False

    @property
    def name(self) -> str:
        """Step name."""
        return f"keycloak-user-{self.key}"

    @property
    def username(self) -> str:
        """The user's name in Keycloak."""
        return f"{PREFIX}-{self.key}"

    @property
    def store_key(self) -> str:
        """Key of the password in the credentials Secret."""
        return keycloak_password_key(self.key)

    def is_present(self, ctx: Context, /) -> bool:
        """The user exists with the wanted attributes, roles and groups that the realm has.

        Its password must be in the credentials Secret. A role or group the realm gets later makes the step apply again.
        """
        admin = for_environment(ctx.env)
        user = admin.user(self.username)
        if user is None or self.store_key not in ctx.store.read():
            return False
        attributes = section(user, "attributes")
        if any(attributes.get(name) != values for name, values in self.attributes.items()):
            return False
        user_id = str(user["id"])
        roles = {str(r["name"]) for r in admin.realm_roles(self.realm_roles)}
        groups = {g for g in self.groups if admin.group_id(g)}
        if not (roles <= admin.user_realm_roles(user_id) and groups <= admin.user_groups(user_id)):
            return False
        client_roles = filter(None, (admin.client_role(c, r) for c, r in self.client_roles))
        return all(str(role["name"]) in admin.user_client_roles(user_id, uuid) for uuid, role in client_roles)

    def apply(self, ctx: Context, /) -> dict[str, str]:
        """Create or update the user with a new password and the wanted roles and groups that exist.

        A realm imported with keycloak.config.skipRoles/skipGroups true has none of the import's roles or
        groups, so a user that should have rights would get none. Partly missing roles are a note (4.10's realm
        drops some by design); a user that wants roles and gets none fails the step, naming the likely cause.
        """
        admin = for_environment(ctx.env)
        password = admin.new_password()
        user = admin.save_user(self.username, password, self.attributes)
        realm_roles = admin.realm_roles(self.realm_roles)
        admin.add_realm_roles(user, realm_roles)
        assigned = len(realm_roles)
        missing = sorted(set(self.realm_roles) - {str(r["name"]) for r in realm_roles})
        for client, role in self.client_roles:
            found = admin.client_role(client, role)
            if found:
                admin.add_client_role(user, *found)
                assigned += 1
            else:
                missing.append(f"{client}:{role}")
        for group in self.groups:
            group_id = admin.group_id(group)
            if group_id:
                admin.join_group(user, group_id)
                assigned += 1
            else:
                missing.append(f"group {group}")
        wanted = self.realm_roles or self.client_roles or self.groups
        if wanted and not assigned:
            msg = (
                f"{self.username} wants roles or groups but the realm has none of them ({', '.join(missing)}): "
                "the realm was imported with skipRoles/skipGroups and step keycloak-roles needs bootstrap wiring"
            )
            raise ValueError(msg)
        if missing:
            ctx.notes.append("not in realm: " + ", ".join(missing))
        return {self.store_key: password}

    def remove(self, ctx: Context, /) -> tuple[str, ...]:
        """Delete the user."""
        admin = for_environment(ctx.env)
        user = admin.user_id(self.username)
        if user:
            admin.delete_user(user)
        return (self.store_key,)


# Attribute of the roles keycloak-roles creates.
CREATED_BY = {PREFIX: ["keycloak-roles"]}


@dataclass(frozen=True)
class KeycloakRoles:
    """The realm and client roles of the test users that the realm lacks, as after keycloak.config.skipRoles true.

    The record lists what the step created ("role" or "client:role"), and each role carries attribute
    CREATED_BY; remove deletes only a recorded role that still has it, so a role that a later realm import
    (skipRoles false) created or rewrote is kept. Roles of clients the realm lacks are left out.
    """

    users: tuple[KeycloakUser, ...]
    name: str = "keycloak-roles"
    requires: tuple[str, ...] = ("keycloak",)
    wiring: bool = True
    store_key: str = f"{PREFIX.replace('-', '_')}_keycloak_roles_record"

    def _missing(self, admin: KeycloakAdmin) -> list[str]:
        """Each wanted role that does not exist, as a record entry."""
        wanted = sorted({r for u in self.users for r in u.realm_roles})
        existing = {str(r["name"]) for r in admin.realm_roles(tuple(wanted))}
        missing = [r for r in wanted if r not in existing]
        for client_id, role in sorted({cr for u in self.users for cr in u.client_roles}):
            if admin.client(client_id) and admin.client_role(client_id, role) is None:
                missing.append(f"{client_id}:{role}")
        return missing

    @staticmethod
    def _client_uuid(admin: KeycloakAdmin, entry: str) -> tuple[str, str | None]:
        """(role, client uuid) of a record entry; the uuid is None for a realm role."""
        client_id, _, role = entry.rpartition(":")
        client = admin.client(client_id) if client_id else None
        return role, str(client["id"]) if client else None

    def _record(self, ctx: Context) -> list[str]:
        return cast("list[str]", json.loads(ctx.store.read().get(self.store_key, "[]")))

    def is_present(self, ctx: Context, /) -> bool:
        """Every wanted role exists."""
        return not self._missing(for_environment(ctx.env))

    def apply(self, ctx: Context, /) -> dict[str, str]:
        """Create the missing roles and add them to the record."""
        admin = for_environment(ctx.env)
        missing = self._missing(admin)
        for entry in missing:
            admin.create_role(*self._client_uuid(admin, entry), CREATED_BY)
        return {self.store_key: json.dumps(self._record(ctx) + missing)}

    def remove(self, ctx: Context, /) -> tuple[str, ...]:
        """Delete the recorded roles that still carry CREATED_BY."""
        admin = for_environment(ctx.env)
        for entry in self._record(ctx):
            name, client_uuid = self._client_uuid(admin, entry)
            if client_uuid is None and ":" in entry:
                continue
            role = admin.role(name, client_uuid)
            if role and section(role, "attributes").get(PREFIX) == CREATED_BY[PREFIX]:
                admin.delete_role(name, client_uuid)
        return (self.store_key,)
