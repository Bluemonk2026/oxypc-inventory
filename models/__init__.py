from .user import User, LoginLog, UserPermission
from .lot import Lot
from .device import Device, StageMovement
from .repair import RepairJob
from .qc import QCCheck
from .sales import Sale, Return
from .spare_parts import SparePart, SparePartPurchase, SparePartConsumption, RAMTracking
from .master import MasterData
from .attendance import Attendance
from .dealers import Dealer, DealerAssignment, DealerCall, DealerOrder, DealerCreditNote
from .telecalling import TelecallingSession, TelecallingRecord
from .whatsapp import WhatsAppSession, WhatsAppMessage
# R-OS v2.0 engine models
from .stage_control import StageMaster, AllowedTransition
from .engines import RepairAttempt, DeviceCosting, SparePartsLedger, DeviceAging, AuditLog
# Location tracking
from .location import StorageLocation, DeviceLocationLog, InventoryAudit, AuditScanItem
# Previously missing from __init__ — Alembic needs ALL models imported to manage their tables
from .iqc_inspection import IQCInspection
from .stock_transfer import StockTransfer
from .work_order import WorkOrder
from .part_request import PartRequest, PartSourcingRequest
from .dispatch_request import TelecallerDispatchRequest
from .stock_validation import StockValidation
from .grn_import import GRNImport
from .market import MarketAvailability
# QA / UAT tracking module
from .qa_uat import (
    QARequirement, QATestCase, QATestExecution,
    QADefect, QAUATScenario, QARelease,
)
# CRM module
from .crm import (
    CRMContact, CRMSourcingDeal, CRMSalesOpportunity,
    CRMQuote, CRMQuoteItem, CRMActivity, GradePriceMatrix,
    CRMPurchaseOrder, CRMPOLineItem,
    SupplierPayment, CustomerReceipt,
)
from .settings import AppSetting
from .api_key import APIKey
from .webhook import Webhook
from .event_log import EventLog
from .cost_config import CostConfig
