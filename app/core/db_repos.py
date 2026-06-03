"""Bundle SQL repositories constructed from one Session."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.repositories.activity_logs_repository import ActivityLogsRepository
from app.repositories.communications_repository import CommunicationsRepository
from app.repositories.data_imports_repository import DataImportsRepository
from app.repositories.pack_codes_repository import PackCodesRepository
from app.repositories.tender_products_repository import TenderProductsRepository
from app.repositories.tenders_repository import TendersRepository
from app.repositories.tenants_db_repository import TenantsDbRepository
from app.repositories.turvo_oauth_repository import TurvoOAuthRepository
from app.repositories.workflow_lifecycles_repository import WorkflowLifecyclesRepository
from app.repositories.workflow_runs_repository import WorkflowRunsRepository


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
    tenants: TenantsDbRepository
    turvo_oauth: TurvoOAuthRepository


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
        tenants=TenantsDbRepository(session),
        turvo_oauth=TurvoOAuthRepository(session),
    )
