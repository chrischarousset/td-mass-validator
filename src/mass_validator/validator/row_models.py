import re
from itertools import chain

import attr
from django.core.exceptions import ValidationError
from django.core.validators import EmailValidator

from .constants import (
    COMPANY_TYPES,
    ERROR_STR,
    ETABLISSMENTS_FIELDS,
    MAX_ETAB_COL,
    MAX_ROLE_COL,
    MIN_ETAB_ROW,
    MIN_ROLE_ROW,
    ROLE_FIELDS,
    VALID_STR,
)
from .helpers import dict_read, format_csv_row, quote

phone_re = re.compile(r"^(0[1-9])(?:[ _.-]?(\d{2})){4}$")

ETABLISSEMENTS_TAB = "Établissements"
ROLES_TAB = "Rôles"

ERROR_FIELD = "field"
ERROR_SIRET_MISSING_FROM_ETAB = "siret_missing_from_etab"
ERROR_TYPES = [ERROR_FIELD, ERROR_SIRET_MISSING_FROM_ETAB]


class BaseRow:
    @property
    def is_valid(self):
        if not self.validated:
            raise Exception("Not validated yet")
        return not self.errors

    def siret_is_valid(self):
        return len(str(self.siret)) == 14

    @classmethod
    def from_dict(cls, idx, the_dict):
        if all([not v for v in the_dict.values()]):  # skip empty rows
            return

        return cls(**the_dict, index=idx)


class BaseRows:
    def __iter__(self):
        yield from self.rows

    def append(self, row):
        if not self.header:
            self.header = row
        else:
            self.rows.append(row)

    def get_errors(self):
        errors = [row.errors for row in self.rows]
        return chain.from_iterable(errors)


@attr.s()
class RowError:
    row_number = attr.ib()
    field_name = attr.ib()
    field_value = attr.ib()
    error_type = attr.ib(default=ERROR_FIELD)

    tab = attr.ib(default="")

    @error_type.validator
    def _check_error_type(self, attribute, value):
        return value in ERROR_TYPES

    def as_str(self):
        return f"{self.field_name.capitalize()} error on row n°{self.row_number} value={self.field_value}"

    def verbose_error_field(self):
        return f"Valeur incorrecte"

    def verbose_error_missing_siret(self):
        return f"Siret absent de l'onglet établissements"

    @property
    def verbose(self):
        if self.error_type == ERROR_SIRET_MISSING_FROM_ETAB:
            return self.verbose_error_missing_siret()
        return self.verbose_error_field()


@attr.s()
class SiretError:
    siret = attr.ib()

    @property
    def verbose(self):
        return "Ce siret est non diffusible"


@attr.s()
class EtabRow(BaseRow):
    index = attr.ib()
    siret = attr.ib(default="")
    gerepid = attr.ib(default="")
    companyTypes = attr.ib(default=attr.Factory(list))
    givenName = attr.ib(default="")
    contactEmail = attr.ib(default="")
    contactPhone = attr.ib(default="")
    webSite = attr.ib(default="")

    errors = attr.ib(default=attr.Factory(list))
    validated = attr.ib(default=False)
    tab_name = ETABLISSEMENTS_TAB

    def as_str(self):
        return f"{self.siret} {self.givenName} {self.contactEmail}"

    def as_list(self):
        return [
            str(self.index),
            self.siret,
            self.gerepid,
            ",".join(self.companyTypes),
            self.givenName,
            self.contactEmail,
            self.contactPhone,
            self.webSite,
            ERROR_STR if not self.is_valid else VALID_STR,
        ]

    def as_csv(self):

        quoted = [
            quote(self.siret),
            quote(self.gerepid),
            ",".join(self.companyTypes),
            quote(self.givenName),
            quote(self.contactEmail),
            quote(self.contactPhone),
            quote(self.webSite),
        ]
        return format_csv_row(quoted)

    def company_types_are_valid(self):
        return all([c_type in COMPANY_TYPES for c_type in self.companyTypes])

    def phone_number_is_valid(self):
        if not self.contactPhone:
            return True
        return phone_re.match(self.contactPhone) is not None

    def email_is_valid(self):
        if not self.contactEmail:
            return True
        try:
            EmailValidator()(
                self.contactEmail,
            )
            return True
        except ValidationError:
            return False

    def validate(self):

        if not self.siret_is_valid():
            self.errors.append(
                RowError(
                    row_number=self.index,
                    field_name="siret",
                    field_value=self.siret,
                    tab=self.tab_name,
                )
            )
        if not self.company_types_are_valid():
            self.errors.append(
                RowError(
                    row_number=self.index,
                    field_name="companyTypes",
                    field_value=self.companyTypes,
                    tab=self.tab_name,
                )
            )
        if not self.phone_number_is_valid():
            self.errors.append(
                RowError(
                    row_number=self.index,
                    field_name="contactPhone",
                    field_value=self.contactPhone,
                    tab=self.tab_name,
                )
            )
        if not self.email_is_valid():
            self.errors.append(
                RowError(
                    row_number=self.index,
                    field_name="contactEmail",
                    field_value=self.contactEmail,
                    tab=self.tab_name,
                )
            )
        self.validated = True


@attr.s()
class EtabRows(BaseRows):
    header = attr.ib(default="")
    rows = attr.ib(default=attr.Factory(list))
    is_valid = attr.ib(default=False)
    siret_errors = attr.ib(default=attr.Factory(list))
    verbose_errors = attr.ib(default=attr.Factory(list))

    def append(self, row):
        if not self.header:
            self.header = row
        else:
            self.rows.append(row)

    def sirets(self):
        return list(set([item.siret for item in self if item.siret]))

    def validate(self):
        self.is_valid = True
        for row in self:
            row.validate()
            if not row.is_valid:
                self.is_valid = False

    def as_csv(self):
        ret = []
        ret.append(format_csv_row([quote(fn) for fn in ETABLISSMENTS_FIELDS]))
        for row in self:
            ret.append(row.as_csv())
        return ret

    @classmethod
    def from_worksheet(cls, worksheet):
        etab_rows = []
        idx = 1
        for row in worksheet.iter_rows(min_row=MIN_ETAB_ROW, max_col=MAX_ETAB_COL):
            data = dict_read(row, ETABLISSMENTS_FIELDS)
            if idx != 1:
                etab_row = EtabRow.from_dict(idx, data)

                if etab_row:
                    etab_rows.append(etab_row)
            idx += 1
        return cls(rows=etab_rows)


@attr.s()
class RoleRow(BaseRow):
    index = attr.ib()
    siret = attr.ib()
    email = attr.ib()
    role = attr.ib()
    errors = attr.ib(default=attr.Factory(list))
    validated = attr.ib(default=False)
    tab_name = ROLES_TAB

    def as_str(self):
        return f"{self.siret} {self.role} {self.email}"

    def as_list(self):
        return [
            str(self.index),
            self.siret,
            self.email,
            self.role,
            ERROR_STR if not self.is_valid else VALID_STR,
        ]

    def as_csv(self):

        quoted = [
            quote(self.siret),
            quote(self.email),
            quote(self.role),
        ]
        return format_csv_row(quoted)

    def role_is_valid(self):
        return self.role in ["MEMBER", "ADMIN"]

    def siret_belongs_to(self, etab_sirets):
        return self.siret in etab_sirets

    def email_is_valid(self):
        if not self.email:
            return False

        try:
            EmailValidator()(
                self.email,
            )
            return True
        except ValidationError:
            return False

    def validate(self, etab_sirets):
        if not self.role_is_valid():
            self.errors.append(
                RowError(
                    row_number=self.index,
                    field_name="role",
                    field_value=self.role,
                    tab=self.tab_name,
                )
            )
        if not self.siret_is_valid():
            self.errors.append(
                RowError(
                    row_number=self.index,
                    field_name="siret",
                    field_value=self.siret,
                    tab=self.tab_name,
                )
            )
        if not self.siret_belongs_to(etab_sirets):
            self.errors.append(
                RowError(
                    row_number=self.index,
                    field_name="siret",
                    field_value=self.siret,
                    tab=ROLES_TAB,
                    error_type=ERROR_SIRET_MISSING_FROM_ETAB,
                )
            )
        if not self.email_is_valid():
            self.errors.append(
                RowError(
                    row_number=self.index,
                    field_name="email",
                    field_value=self.email,
                    tab=self.tab_name,
                )
            )
        self.validated = True


@attr.s()
class RoleRows(BaseRows):
    header = attr.ib(default="")
    rows = attr.ib(default=attr.Factory(list))

    is_valid = attr.ib(default=False)
    verbose_errors = attr.ib(default=attr.Factory(list))

    def sirets(self):
        return list(set([item.siret for item in self if item.siret]))

    def as_csv(self):
        ret = []
        ret.append(format_csv_row([quote(fn) for fn in ROLE_FIELDS]))
        for row in self:
            ret.append(row.as_csv())
        return ret

    def validate(self, etab_sirets):

        self.is_valid = True
        for row in self:
            row.validate(etab_sirets)
            if not row.is_valid:
                self.is_valid = False

    @classmethod
    def from_worksheet(cls, worksheet):
        role_rows = []
        idx = 1
        for row in worksheet.iter_rows(min_row=MIN_ROLE_ROW, max_col=MAX_ROLE_COL):
            data = dict_read(row, ROLE_FIELDS)
            if idx != 1:
                role_row = RoleRow.from_dict(idx, data)

                if role_row:
                    role_rows.append(role_row)
            idx += 1
        return cls(rows=role_rows)