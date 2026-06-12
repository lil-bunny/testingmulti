"""Tests for POD lifecycle entries in the error catalog."""

from __future__ import annotations

import pytest

from app.domain.error_catalog import (
    BusinessError,
    ErrorCategory,
    IntegrationError,
    SystemError,
    error_category,
    error_description,
    has_workflow_error,
    resolve_error_code,
    workflow_error_payload,
)


# ---------------------------------------------------------------------------
# BusinessError POD members
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("member,expected_code", [
    (BusinessError.POD_ATTACHMENT_UPLOAD_FAILED, "pod_attachment_upload_failed"),
    (BusinessError.POD_EXTRACTION_EMPTY, "pod_extraction_empty"),
    (BusinessError.POD_VS_RATECON_VALIDATION_FAILED, "pod_vs_ratecon_validation_failed"),
    (BusinessError.MISSING_POD_DATA, "missing_pod_data"),
    (BusinessError.MISSING_RATECON_DATA, "missing_ratecon_data"),
])
def test_business_error_wire_code(member, expected_code):
    assert member.value == expected_code


@pytest.mark.parametrize("member", [
    BusinessError.POD_ATTACHMENT_UPLOAD_FAILED,
    BusinessError.POD_EXTRACTION_EMPTY,
    BusinessError.POD_VS_RATECON_VALIDATION_FAILED,
    BusinessError.MISSING_POD_DATA,
    BusinessError.MISSING_RATECON_DATA,
])
def test_business_error_description_non_empty(member):
    assert member.description


@pytest.mark.parametrize("member", [
    BusinessError.POD_ATTACHMENT_UPLOAD_FAILED,
    BusinessError.POD_EXTRACTION_EMPTY,
    BusinessError.POD_VS_RATECON_VALIDATION_FAILED,
    BusinessError.MISSING_POD_DATA,
    BusinessError.MISSING_RATECON_DATA,
])
def test_business_error_category(member):
    assert member.category == ErrorCategory.BUSINESS


# ---------------------------------------------------------------------------
# IntegrationError POD members
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("member,expected_code", [
    (IntegrationError.POD_S3_DOWNLOAD_FAILED, "pod_s3_download_failed"),
    (IntegrationError.TMS_POD_UPLOAD_FAILED, "tms_pod_upload_failed"),
])
def test_integration_error_wire_code(member, expected_code):
    assert member.value == expected_code


@pytest.mark.parametrize("member", [
    IntegrationError.POD_S3_DOWNLOAD_FAILED,
    IntegrationError.TMS_POD_UPLOAD_FAILED,
])
def test_integration_error_description_non_empty(member):
    assert member.description


@pytest.mark.parametrize("member", [
    IntegrationError.POD_S3_DOWNLOAD_FAILED,
    IntegrationError.TMS_POD_UPLOAD_FAILED,
])
def test_integration_error_category(member):
    assert member.category == ErrorCategory.INTEGRATION


# ---------------------------------------------------------------------------
# SystemError POD member
# ---------------------------------------------------------------------------

def test_system_error_missing_shipment_id_wire_code():
    assert SystemError.MISSING_SHIPMENT_ID.value == "missing_shipment_id"


def test_system_error_missing_shipment_id_description():
    assert SystemError.MISSING_SHIPMENT_ID.description


def test_system_error_missing_shipment_id_category():
    assert SystemError.MISSING_SHIPMENT_ID.category == ErrorCategory.SYSTEM


# ---------------------------------------------------------------------------
# resolve_error_code round-trips
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("code", [
    "pod_attachment_upload_failed",
    "pod_extraction_empty",
    "pod_vs_ratecon_validation_failed",
    "missing_pod_data",
    "missing_ratecon_data",
    "pod_s3_download_failed",
    "tms_pod_upload_failed",
    "missing_shipment_id",
])
def test_resolve_error_code_round_trip(code):
    resolved = resolve_error_code(code)
    assert resolved is not None
    assert resolved.value == code


# ---------------------------------------------------------------------------
# error_description and error_category helpers
# ---------------------------------------------------------------------------

def test_error_description_by_string():
    desc = error_description("pod_extraction_empty")
    assert desc == BusinessError.POD_EXTRACTION_EMPTY.description


def test_error_category_business_by_string():
    cat = error_category("pod_attachment_upload_failed")
    assert cat == ErrorCategory.BUSINESS


def test_error_category_integration_by_string():
    cat = error_category("tms_pod_upload_failed")
    assert cat == ErrorCategory.INTEGRATION


def test_error_category_system_by_string():
    cat = error_category("missing_shipment_id")
    assert cat == ErrorCategory.SYSTEM


# ---------------------------------------------------------------------------
# has_workflow_error with new codes
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("code", [
    "pod_attachment_upload_failed",
    "tms_pod_upload_failed",
    "missing_shipment_id",
])
def test_has_workflow_error_true_for_pod_codes(code):
    payload = workflow_error_payload(
        code=code,
        message="some message",
    )
    assert has_workflow_error({"error": payload})
