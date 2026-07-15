"""Bundle SQL repositories constructed from one Session."""

from __future__ import annotations

from dataclasses import dataclass


from app.repositories.activity_logs_repository import ActivityLogsRepository
from app.repositories.communications_repository import CommunicationsRepository
from app.repositories.data_imports_repository import DataImportsRepository
from app.repositories.document_analysis_repository import DocumentAnalysisRepository
from app.repositories.documents_repository import DocumentsRepository
from app.repositories.locations_repository import LocationsRepository
from app.repositories.pack_codes_repository import PackCodesRepository
from app.repositories.routing_guide_repository import RoutingGuideRepository
from app.repositories.shipments_repository import ShipmentsRepository
from app.repositories.tender_products_repository import TenderProductsRepository
from app.repositories.tenders_repository import TendersRepository
from app.repositories.tenants_db_repository import TenantsDbRepository
from app.repositories.turvo_oauth_repository import TurvoOAuthRepository
from app.repositories.workflow_lifecycles_repository import WorkflowLifecyclesRepository
from app.repositories.workflow_runs_repository import WorkflowRunsRepository
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


@dataclass
class DbRepos:
    session: Session
    activity_logs: ActivityLogsRepository
    workflow_lifecycles: WorkflowLifecyclesRepository
    workflow_runs: WorkflowRunsRepository
    tenders: TendersRepository
    tender_products: TenderProductsRepository
    pack_codes: PackCodesRepository
    data_imports: DataImportsRepository
    communications: CommunicationsRepository
    documents: DocumentsRepository
    document_analysis: DocumentAnalysisRepository
    tenants: TenantsDbRepository
    turvo_oauth: TurvoOAuthRepository
    shipments: ShipmentsRepository
    locations: LocationsRepository
    routing_guide: RoutingGuideRepository


def build_db_repos(session: Session) -> DbRepos:
    return DbRepos(
        session=session,
        activity_logs=ActivityLogsRepository(session),
        workflow_lifecycles=WorkflowLifecyclesRepository(session),
        workflow_runs=WorkflowRunsRepository(session),
        tenders=TendersRepository(session),
        tender_products=TenderProductsRepository(session),
        pack_codes=PackCodesRepository(session),
        data_imports=DataImportsRepository(session),
        communications=CommunicationsRepository(session),
        documents=DocumentsRepository(session),
        document_analysis=DocumentAnalysisRepository(session),
        tenants=TenantsDbRepository(session),
        turvo_oauth=TurvoOAuthRepository(session),
        shipments=ShipmentsRepository(session),
        locations=LocationsRepository(session),
        routing_guide=RoutingGuideRepository(session),
    )
