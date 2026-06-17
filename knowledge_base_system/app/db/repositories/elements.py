import logging

from app.core.models import (
    ElementType,
    ParsedElement,
    SourceLocation,
)
from app.db.models import DbParsedElement
from app.db.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


class ParsedElementRepository(BaseRepository):
    """Persist and query ParsedElement records in PostgreSQL."""

    def _to_db(self, el: ParsedElement) -> DbParsedElement:
        return DbParsedElement(
            element_id=el.element_id,
            doc_id=el.doc_id,
            doc_version=el.doc_version,
            parent_element_id=el.parent_element_id,
            sequence_order=el.sequence_order,
            element_type=el.element_type.value,
            text=el.text,
            structured_data=el.structured_data,
            asset_ids=el.asset_ids,
            embedded_doc_id=el.embedded_doc_id,
            source_location=el.source_location.model_dump(mode="json"),
            meta=el.metadata,
        )

    def _from_db(self, db_el: DbParsedElement) -> ParsedElement:
        return ParsedElement(
            element_id=db_el.element_id,
            doc_id=db_el.doc_id,
            doc_version=db_el.doc_version,
            parent_element_id=db_el.parent_element_id,
            sequence_order=db_el.sequence_order,
            element_type=ElementType(db_el.element_type),
            text=db_el.text,
            structured_data=db_el.structured_data,
            asset_ids=db_el.asset_ids or [],
            embedded_doc_id=db_el.embedded_doc_id,
            source_location=SourceLocation.model_validate(db_el.source_location or {}),
            metadata=db_el.meta or {},
        )

    def create_batch(self, elements: list[ParsedElement]) -> list[ParsedElement]:
        with self._session() as session:
            for el in elements:
                session.merge(self._to_db(el))
            session.commit()
            return elements

    def get_by_doc_id(self, doc_id: str) -> list[ParsedElement]:
        with self._session() as session:
            db_els = (
                session.query(DbParsedElement)
                .filter_by(doc_id=doc_id)
                .order_by(DbParsedElement.sequence_order)
                .all()
            )
            return [self._from_db(db_el) for db_el in db_els]
