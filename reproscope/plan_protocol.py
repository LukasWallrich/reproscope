"""Closed compatibility rules for independently executable analysis plans.

Only explicit, recognised declarations are translated. Raw plans are preserved;
unknown prose remains unsupported and is never treated as a computation failure.
"""
from copy import deepcopy
import re

VERSION = "direct-plan-1"
METHOD_FIELDS = ("analysis_id", "status", "family", "file", "table", "header", "x", "y",
                 "id_column", "equal_var", "alternative", "transformations", "missingness",
                 "numeric_parsing", "group_column", "group_values", "contrast", "members", "df_per_subject", "nesting", "aggregation", "covariates", "predictors", "coefficient", "coefficient_field", "intercept", "covariance", "confidence_level")


def normalise(raw):
    plan = deepcopy(raw)
    changes, unsupported = [], []
    if plan.get("family") == "pearson_correlation":
        plan["family"] = "correlation"
        changes.append("pearson_family_name")
    missing = plan.get("missingness")
    if missing in ("strict float parsing; blank/whitespace -> missing; complete pairs only",
                   "complete cases on the analysed columns"):
        plan.update(missingness="complete_cases", numeric_parsing="strict_float_blank_missing")
        changes.append("explicit_complete_case_declaration")
    elif missing == "none present":
        plan["missingness"] = "complete_explicit_sample"
        changes.append("explicit_no_missing_declaration")
    elif missing not in (None, "complete_explicit_sample", "complete_cases"):
        unsupported.append("unrecognised missingness declaration")
    transformations = plan.get("transformations")
    if transformations == "none (per-subject estimates used as deposited; blank cells -> missing)":
        plan["transformations"] = []
        plan["numeric_parsing"] = "strict_float_blank_missing"
        changes.append("explicit_deposited_values_declaration")
    elif transformations:
        compact = lambda s: re.sub(r"\s+", "", s)
        wanted = f"d={plan.get('x')}-{plan.get('y')};dz=mean(d)/sd(d)"
        if (plan.get("family") == "paired_t" and isinstance(transformations, list)
                and len(transformations) == 1 and isinstance(transformations[0], str)
                and compact(transformations[0]) == wanted):
            plan["transformations"] = []
            changes.append("intrinsic_paired_difference_and_dz")
        else:
            unsupported.append("unrecognised transformations declaration")
    return plan, {"version": VERSION, "rules": changes}, unsupported


# The next-generation task uses closed fields. Legacy plans retain the bounded
# compatibility rules above; a versioned plan never receives prose normalisation.
from typing import Literal, Annotated
from pydantic import BaseModel, ConfigDict, Field, model_validator


class UnsupportedPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    analysis_id: str = Field(min_length=1)
    status: Literal["unsupported"]
    reason: str = Field(min_length=1)


class DirectPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    analysis_id: str = Field(min_length=1)
    status: Literal["supported"]
    family: Literal["paired_t", "independent_t", "one_sample_t", "correlation"]
    file: str = Field(min_length=1)
    table: str | int | None
    header: int | None
    x: str = Field(min_length=1)
    y: str | None
    id_column: str | None
    included_ids: list[str | int | float] | None
    equal_var: bool
    alternative: Literal["two-sided", "greater", "less"]
    transformations: list[str] = Field(max_length=0)
    missingness: Literal["complete_cases", "complete_explicit_sample"]
    numeric_parsing: Literal["strict_float", "strict_float_blank_missing"]
    group_column: str | None
    group_values: list[str | int | float] | None
    contrast: str = Field(min_length=1)
    null_value: float | None = None

    @model_validator(mode="after")
    def coherent(self):
        from pathlib import PurePosixPath
        path = PurePosixPath(self.file)
        if path.is_absolute() or ".." in path.parts or not path.parts or path.parts[0] != "data":
            raise ValueError("file must be a relative path under data/")
        if path.suffix.lower() == ".csv" and self.header != 0:
            raise ValueError("direct CSV plans require the first row as header, encoded as zero-based header=0")
        if self.family == "independent_t":
            if not self.group_column or not self.group_values or len(self.group_values) != 2 or len(set(self.group_values)) != 2:
                raise ValueError("independent t requires two distinct ordered group values")
            if self.y is not None:
                raise ValueError("independent t uses x and ordered groups, not y")
        elif self.family == "one_sample_t":
            if self.y is not None or self.null_value is None or self.group_column is not None or self.group_values is not None:
                raise ValueError("one-sample t requires scalar x, a declared null value and no y/groups")
        elif not self.y or self.group_column is not None or self.group_values is not None:
            raise ValueError("paired/correlation plans require scalar y and no grouping fields")
        if self.included_ids is not None:
            if not self.id_column or len(set(self.included_ids)) != len(self.included_ids):
                raise ValueError("explicit sample requires an identifier and unique IDs")
        return self


class PlanDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    protocol_version: Literal["direct-plan-2"]
    analyses: list[Annotated[DirectPlan | UnsupportedPlan, Field(discriminator="status")]]

    @model_validator(mode="after")
    def unique_ids(self):
        ids = [a.analysis_id for a in self.analyses]
        if len(ids) != len(set(ids)):
            raise ValueError("analysis IDs must be unique")
        return self


class FamilyPlan(BaseModel):
    """Named scalar analyses preserve member identity through vector outputs."""
    model_config = ConfigDict(extra="forbid", strict=True)
    analysis_id: str = Field(min_length=1)
    status: Literal["supported"]
    family: Literal["paired_t_family", "correlation_family"]
    members: list[DirectPlan] = Field(min_length=2)

    @model_validator(mode="after")
    def coherent(self):
        expected = "paired_t" if self.family == "paired_t_family" else "correlation"
        ids = [m.analysis_id for m in self.members]
        if len(set(ids)) != len(ids) or any(m.family != expected for m in self.members):
            raise ValueError("family requires distinct named members of its declared scalar family")
        return self


class LikelihoodPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    analysis_id: str = Field(min_length=1)
    status: Literal["supported"]
    family: Literal["likelihood_ratio"]
    file: str
    table: str | int | None
    header: int | None
    x: str  # maximised log likelihood of larger model per participant
    y: str  # maximised log likelihood of nested smaller model per participant
    id_column: str
    included_ids: list[str | int | float] | None
    missingness: Literal["complete_cases", "complete_explicit_sample"]
    numeric_parsing: Literal["strict_float", "strict_float_blank_missing"]
    df_per_subject: int = Field(gt=0)
    nesting: Literal["larger_contains_smaller"]
    aggregation: Literal["sum_subject_loglikelihoods"]
    contrast: str = Field(min_length=1)

    @model_validator(mode="after")
    def coherent(self):
        from pathlib import PurePosixPath
        p=PurePosixPath(self.file)
        if p.is_absolute() or '..' in p.parts or not p.parts or p.parts[0]!='data':
            raise ValueError('file must be relative under data/')
        if p.suffix.lower()=='.csv' and self.header!=0:
            raise ValueError('CSV header must be zero')
        if not self.x or not self.y or self.x==self.y or not self.id_column:
            raise ValueError('likelihood comparison needs distinct columns and subject IDs')
        if self.included_ids is not None and len(set(self.included_ids))!=len(self.included_ids):
            raise ValueError('duplicate selected IDs')
        return self


class AdjustedPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    analysis_id: str = Field(min_length=1)
    status: Literal["supported"]
    family: Literal["partial_correlation", "linear_regression"]
    file: str
    table: str | int | None
    header: int | None
    x: str
    y: str | None
    covariates: list[str]
    predictors: list[str]
    coefficient: str | None
    coefficient_field: str | None
    id_column: str | None
    included_ids: list[str | int | float] | None
    missingness: Literal["complete_cases", "complete_explicit_sample"]
    numeric_parsing: Literal["strict_float", "strict_float_blank_missing"]
    alternative: Literal["two-sided"]
    transformations: list[str] = Field(max_length=0)
    intercept: Literal[True]
    covariance: Literal["classical"]
    confidence_level: Literal[0.95]

    @model_validator(mode="after")
    def coherent(self):
        from pathlib import PurePosixPath
        p=PurePosixPath(self.file)
        if p.is_absolute() or ".." in p.parts or not p.parts or p.parts[0]!='data':
            raise ValueError('adjusted plan requires a supplied data path')
        if p.suffix.lower()=='.csv' and self.header!=0:raise ValueError('CSV header must be zero')
        if self.family=='partial_correlation':
            if not self.y or not self.covariates or self.predictors or self.coefficient or self.coefficient_field:
                raise ValueError('partial correlation requires x, y and covariates only')
            columns=[self.x,self.y]+self.covariates
        else:
            if self.y or self.covariates or not self.predictors:
                raise ValueError('regression requires outcome x and the complete predictor list')
            if self.coefficient is not None and (self.coefficient not in self.predictors or not self.coefficient_field):
                raise ValueError('coefficient requires a predictor and its intake binding field')
            columns=[self.x]+self.predictors
        if len(set(columns))!=len(columns):raise ValueError('duplicate adjusted model columns')
        if self.included_ids is not None and (not self.id_column or len(set(self.included_ids))!=len(self.included_ids)):
            raise ValueError('sample requires unique deposited IDs')
        return self


class ExtendedPlanDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    protocol_version: Literal["direct-plan-3"]
    analyses: list[DirectPlan | FamilyPlan | LikelihoodPlan | AdjustedPlan | UnsupportedPlan]

    @model_validator(mode="after")
    def unique_ids(self):
        ids=[a.analysis_id for a in self.analyses]
        if len(ids)!=len(set(ids)):
            raise ValueError('analysis IDs must be unique')
        return self


def validate_document(document):
    cls=ExtendedPlanDocument if document.get('protocol_version')=='direct-plan-3' else PlanDocument
    if cls is ExtendedPlanDocument:
        # Validate the declared family, avoiding thousands of irrelevant union
        # branch errors in model repair feedback for a single extra field.
        from pydantic import ValidationError
        import json
        errors=[]
        for index,record in enumerate(document.get('analyses',[])):
            if not isinstance(record,dict):continue
            family=record.get('family')
            target=(UnsupportedPlan if record.get('status')=='unsupported' else
                    AdjustedPlan if family in {'partial_correlation','linear_regression'} else
                    FamilyPlan if family in {'paired_t_family','correlation_family'} else
                    LikelihoodPlan if family=='likelihood_ratio' else
                    DirectPlan if family in {'paired_t','independent_t','one_sample_t','correlation'} else None)
            if target is None:
                errors.append({'analysis':record.get('analysis_id',index),'field':'family','message':'unknown declared family or status'})
                continue
            try:target.model_validate(record)
            except ValidationError as exc:
                errors.extend({'analysis':record.get('analysis_id',index),'field':'.'.join(map(str,e['loc'])),'message':e['msg']}
                              for e in exc.errors(include_input=False,include_url=False))
        if errors:raise ValueError('analysis plan schema errors: '+json.dumps(errors))
    return cls.model_validate(document)


def scalar_members(plan):
    return plan['members'] if plan.get('family') in {'paired_t_family','correlation_family'} else [plan]
