"""Generate synthetic SOW + Change Order + MSSA contract chains as PDFs.

Used by the knowledge-assistant-demo to exercise hierarchical doc relationships
(MSSA umbrella → multiple SOWs → optional Change Orders amending each SOW)
that real-world contract retrieval has to handle but which the public CUAD
corpus does not naturally include.
"""

from dataclasses import dataclass, field
import random
from pathlib import Path
from typing import Any

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.lib import colors


@dataclass
class ContractChain:
    mssa_id: str
    sows: list[dict[str, Any]] = field(default_factory=list)
    change_orders: list[dict[str, Any]] = field(default_factory=list)


def validate_chain(chain: ContractChain) -> list[str]:
    errors: list[str] = []
    sow_ids = {s["sow_id"] for s in chain.sows}
    for co in chain.change_orders:
        if co["amends_sow_id"] not in sow_ids:
            errors.append(
                f"CO {co['co_id']} references missing SOW {co['amends_sow_id']}"
            )
    return errors


_CLIENTS = ["Acme-Corp", "Globex", "Initech", "Umbrella", "Soylent"]
_SCOPES = [
    "Phase 1 platform implementation",
    "Discovery and architecture",
    "Data migration and validation",
    "Ongoing support and managed services",
]


def build_chain(seed: int) -> ContractChain:
    rng = random.Random(seed)
    client = rng.choice(_CLIENTS)
    mssa_id = f"MSSA-{client}"
    n_sows = rng.randint(2, 3)
    sows = [
        {
            "sow_id": f"SOW-2024-{i + 1:02d}-{client}",
            "amount_usd": rng.choice([150000, 250000, 400000, 750000]),
            "scope": rng.choice(_SCOPES),
            "start_date": "2024-01-15",
            "end_date": "2024-12-31",
        }
        for i in range(n_sows)
    ]
    n_cos = rng.randint(1, 2)
    cos = [
        {
            "co_id": f"CO-{client}-{i + 1:03d}",
            "amends_sow_id": rng.choice(sows)["sow_id"],
            "delta_usd": rng.choice([25000, 50000, 100000]),
            "reason": "Expanded scope per client request",
        }
        for i in range(n_cos)
    ]
    return ContractChain(mssa_id=mssa_id, sows=sows, change_orders=cos)


def _render_mssa(path: Path, mssa_id: str) -> None:
    doc = SimpleDocTemplate(str(path), pagesize=LETTER)
    styles = getSampleStyleSheet()
    flow = [
        Paragraph(f"MASTER SERVICES AGREEMENT — {mssa_id}", styles["Title"]),
        Spacer(1, 12),
        Paragraph(
            "This Master Services Agreement governs all Statements of Work "
            "executed thereunder.",
            styles["BodyText"],
        ),
        Spacer(1, 12),
        Paragraph("1. Term and Termination", styles["Heading2"]),
        Paragraph(
            "Either party may terminate with 60 days written notice.",
            styles["BodyText"],
        ),
        Paragraph("2. Offshoring", styles["Heading2"]),
        Paragraph(
            "Offshoring requires prior written consent from Client.",
            styles["BodyText"],
        ),
        Paragraph("3. Confidentiality", styles["Heading2"]),
        Paragraph(
            "All shared materials remain confidential for 5 years post-termination.",
            styles["BodyText"],
        ),
    ]
    doc.build(flow)


def _render_sow(path: Path, sow: dict[str, Any], mssa_id: str) -> None:
    doc = SimpleDocTemplate(str(path), pagesize=LETTER)
    styles = getSampleStyleSheet()
    flow = [
        Paragraph(f"STATEMENT OF WORK — {sow['sow_id']}", styles["Title"]),
        Spacer(1, 12),
        Paragraph(f"Governed by: {mssa_id}", styles["BodyText"]),
        Spacer(1, 12),
        Paragraph(f"Scope: {sow['scope']}", styles["BodyText"]),
        Spacer(1, 12),
    ]
    table = Table(
        [
            ["Field", "Value"],
            ["Total Amount", f"${sow['amount_usd']:,}"],
            ["Start Date", sow["start_date"]],
            ["End Date", sow["end_date"]],
        ],
        colWidths=[150, 200],
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
            ]
        )
    )
    flow.append(table)
    flow.append(Spacer(1, 24))
    flow.append(Paragraph("Signatures:", styles["Heading2"]))
    flow.append(Paragraph("Client: ____________________", styles["BodyText"]))
    flow.append(Paragraph("Provider: ____________________", styles["BodyText"]))
    doc.build(flow)


def _render_co(path: Path, co: dict[str, Any], mssa_id: str) -> None:
    doc = SimpleDocTemplate(str(path), pagesize=LETTER)
    styles = getSampleStyleSheet()
    flow = [
        Paragraph(f"CHANGE ORDER — {co['co_id']}", styles["Title"]),
        Spacer(1, 12),
        Paragraph(f"Amends: {co['amends_sow_id']}", styles["BodyText"]),
        Paragraph(f"Governed by: {mssa_id}", styles["BodyText"]),
        Spacer(1, 12),
        Paragraph(f"Reason: {co['reason']}", styles["BodyText"]),
        Spacer(1, 12),
        Paragraph(f"Additional amount: ${co['delta_usd']:,}", styles["BodyText"]),
    ]
    doc.build(flow)


def render_chain(chain: ContractChain, out_dir: Path) -> list[Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []

    mssa_path = out_dir / f"{chain.mssa_id}.pdf"
    _render_mssa(mssa_path, chain.mssa_id)
    paths.append(mssa_path)

    for sow in chain.sows:
        sow_path = out_dir / f"{sow['sow_id']}.pdf"
        _render_sow(sow_path, sow, chain.mssa_id)
        paths.append(sow_path)

    for co in chain.change_orders:
        co_path = out_dir / f"{co['co_id']}.pdf"
        _render_co(co_path, co, chain.mssa_id)
        paths.append(co_path)

    return paths
