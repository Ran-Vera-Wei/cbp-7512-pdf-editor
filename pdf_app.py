from __future__ import annotations

import io
import json
import re
import zipfile
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pypdfium2 as pdfium
import streamlit as st
from PIL import Image, ImageDraw
from pypdf import PdfReader
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas


PAGE_WIDTH = 612.0
PAGE_HEIGHT = 792.0
FONT = "Helvetica"
TABLE_FONT_SIZE = 6.5
TABLE_LEADING = 8.65
TABLE_TOP = 322.0
TABLE_BOTTOM = 426.0
RENDER_DPI = 300
DESCRIPTION_VALUE = "SHOES, FOOTWEAR WOMEN'S DRESSES MEN'S SHIRTS"
FLAG_VALUE = "US"
PORT_CHOICES = {
    "CN": "57000 - CHINA(MAINLAND)",
    "HK": "HONG KONG - 58201",
}
CLEAR_BOXES = (
    (294, 146, 408, 159.5),  # 1. Car number and initial
    (68, 189.0, 460.0, 204.8),  # 2. Consignee text area; preserve adjacent note and underline
    (290, 241, 359, 251.6),  # 3. Flag
    (111, 216.5, 293.5, 228.7),  # 4. Foreign port of lading
    (490.5, 236.0, 592.0, 248.8),  # Last foreign port value; preserve the underline
    (20, TABLE_TOP - 1, 88, TABLE_BOTTOM),  # 6. Marks and packages
    (93, TABLE_TOP - 1, 316, TABLE_BOTTOM),  # 5. Description and quantity
    (320, TABLE_TOP - 1, 395, TABLE_BOTTOM),  # 7. Gross weight
    (399, TABLE_TOP - 1, 463, TABLE_BOTTOM),  # 8. Value
)


class ProcessingError(Exception):
    """A user-correctable PDF or form input problem."""


@dataclass(frozen=True)
class TextBlock:
    text: str
    x: float
    top: float
    width: float
    height: float


def _check_supported_text(text: str, label: str) -> None:
    try:
        text.encode("cp1252")
    except UnicodeEncodeError as exc:
        raise ProcessingError(
            f"{label} contains a character that this CBP form font cannot display. Use standard Latin characters and punctuation."
        ) from exc


def _wrap_line(text: str, max_width: float, font_size: float) -> list[str]:
    words = text.split()
    if not words:
        return [""]

    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if stringWidth(candidate, FONT, font_size) <= max_width:
            current = candidate
            continue

        if current:
            lines.append(current)
            current = ""

        if stringWidth(word, FONT, font_size) <= max_width:
            current = word
            continue

        part = ""
        for character in word:
            if part and stringWidth(part + character, FONT, font_size) > max_width:
                lines.append(part)
                part = character
            else:
                part += character
        current = part

    if current or not lines:
        lines.append(current)
    return lines


def _wrapped_lines(text: str, max_width: float, font_size: float) -> list[str]:
    lines: list[str] = []
    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        lines.extend(_wrap_line(raw_line, max_width, font_size))
    while lines and not lines[-1]:
        lines.pop()
    return lines


def _draw_text(pdf_canvas: canvas.Canvas, text: str, x: float, top: float, font_size: float) -> None:
    if not text:
        return
    pdf_canvas.setFillColorRGB(0, 0, 0)
    pdf_canvas.setFont(FONT, font_size)
    baseline = PAGE_HEIGHT - top - font_size * 0.73
    pdf_canvas.drawString(x, baseline, text)


def _draw_single_line(
    pdf_canvas: canvas.Canvas,
    text: str,
    *,
    x: float,
    top: float,
    max_width: float,
    preferred_size: float = 9.75,
    min_size: float = 6.0,
    label: str,
) -> None:
    _check_supported_text(text, label)
    size = preferred_size
    while size >= min_size and stringWidth(text, FONT, size) > max_width:
        size -= 0.25
    if stringWidth(text, FONT, size) > max_width:
        raise ProcessingError(f"{label} is too long to fit in its field.")
    _draw_text(pdf_canvas, text, x, top, size)


def _draw_consignee(pdf_canvas: canvas.Canvas, text: str) -> None:
    _check_supported_text(text, "Consignee")
    max_width = 385
    size = 7.0
    lines = _wrapped_lines(text, max_width, size)
    truncated = len(lines) > 2
    lines = lines[:2]
    if truncated and lines:
        lines[-1] = _truncate_line(f"{lines[-1]}...", max_width, size)
    for index, line in enumerate(lines):
        _draw_text(pdf_canvas, line, 72.5, 190.5 + index * 8.0, size)


def _truncate_line(text: str, max_width: float, font_size: float) -> str:
    suffix = "..."
    candidate = text.rstrip()
    while candidate and stringWidth(candidate + suffix, FONT, font_size) > max_width:
        candidate = candidate[:-1].rstrip()
    return f"{candidate}{suffix}"


def _draw_block(pdf_canvas: canvas.Canvas, block: TextBlock, *, label: str) -> None:
    _check_supported_text(block.text, label)
    lines = _wrapped_lines(block.text, block.width, TABLE_FONT_SIZE)
    max_lines = max(1, int((block.height - 2) // TABLE_LEADING))
    if len(lines) > max_lines:
        raise ProcessingError(
            f"{label} has {len(lines)} wrapped lines, but the form area holds {max_lines}. Shorten the text."
        )
    for index, line in enumerate(lines):
        _draw_text(pdf_canvas, line, block.x, block.top + index * TABLE_LEADING, TABLE_FONT_SIZE)


def _build_output(values: dict[str, str], background: Image.Image) -> bytes:
    overlay = io.BytesIO()
    pdf_canvas = canvas.Canvas(overlay, pagesize=(PAGE_WIDTH, PAGE_HEIGHT), pageCompression=1)
    pdf_canvas.drawImage(ImageReader(background), 0, 0, width=PAGE_WIDTH, height=PAGE_HEIGHT)

    _draw_single_line(pdf_canvas, values["export_awb"], x=297.0, top=149.2, max_width=106, label="Export AWB #")
    _draw_consignee(pdf_canvas, values["consignee"])
    _draw_single_line(
        pdf_canvas,
        FLAG_VALUE,
        x=293.2,
        top=241.3,
        max_width=65,
        preferred_size=8.0,
        label="Flag",
    )
    _draw_single_line(
        pdf_canvas,
        values["foreign_port"],
        x=124.0,
        top=218.0,
        max_width=166,
        label="Foreign port of lading",
    )
    _draw_single_line(
        pdf_canvas,
        values["foreign_port"],
        x=493.0,
        top=241.3,
        max_width=97.0,
        label="Last foreign port",
    )
    _draw_block(
        pdf_canvas,
        TextBlock(values["number_of_packages"], x=21.5, top=TABLE_TOP, width=64, height=TABLE_BOTTOM - TABLE_TOP),
        label="Marks and package numbers (6)",
    )
    _draw_block(
        pdf_canvas,
        TextBlock(DESCRIPTION_VALUE, x=95.4, top=TABLE_TOP, width=218, height=TABLE_BOTTOM - TABLE_TOP),
        label="Description and quantity (5)",
    )
    _draw_block(
        pdf_canvas,
        TextBlock(values["gross_weight"], x=322.6, top=TABLE_TOP, width=69, height=TABLE_BOTTOM - TABLE_TOP),
        label="Gross weight (7)",
    )
    _draw_block(
        pdf_canvas,
        TextBlock(values["value"], x=400.2, top=TABLE_TOP, width=59, height=TABLE_BOTTOM - TABLE_TOP),
        label="Value (8)",
    )

    pdf_canvas.save()
    return overlay.getvalue()


def process_pdf(pdf_bytes: bytes, values: dict[str, str]) -> bytes:
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes), strict=False)
    except Exception as exc:
        raise ProcessingError("The uploaded file could not be read as a PDF.") from exc

    if reader.is_encrypted:
        raise ProcessingError("This PDF is password-protected. Upload an unlocked copy.")
    if len(reader.pages) != 1:
        raise ProcessingError("Upload a one-page CBP Form 7512 PDF.")

    first_page = reader.pages[0]
    width = float(first_page.mediabox.width)
    height = float(first_page.mediabox.height)
    if abs(width - PAGE_WIDTH) > 1 or abs(height - PAGE_HEIGHT) > 1 or int(first_page.get("/Rotate", 0)) % 360:
        raise ProcessingError("This layout only supports the portrait, Letter-size CBP Form 7512 shown in the reference.")
    page_text = (first_page.extract_text() or "").casefold()
    if "transportation entry and manifest" not in page_text or "cbp form 7512" not in page_text:
        raise ProcessingError("The uploaded PDF does not appear to be the CBP Form 7512 in the supplied reference.")

    try:
        pdfium_document = pdfium.PdfDocument(pdf_bytes)
        rendered_page = pdfium_document[0]
        image = rendered_page.render(scale=RENDER_DPI / 72).to_pil().convert("RGB")
        rendered_page.close()
        pdfium_document.close()
    except Exception as exc:
        raise ProcessingError("PDFium could not render this file. Upload an unlocked, readable PDF.") from exc

    draw = ImageDraw.Draw(image)
    scale_x = image.width / PAGE_WIDTH
    scale_y = image.height / PAGE_HEIGHT
    for x0, top, x1, bottom in CLEAR_BOXES:
        draw.rectangle(
            (
                round(x0 * scale_x),
                round(top * scale_y),
                round(x1 * scale_x),
                round(bottom * scale_y),
            ),
            fill=(255, 255, 255),
        )

    return _build_output(values, image)


def safe_archive_name(awb: str) -> str:
    safe_awb = re.sub(r"[^A-Za-z0-9._-]+", "", awb.strip()).strip("._-")
    if not safe_awb:
        raise ProcessingError("Enter a valid Export AWB #.")
    return f"{safe_awb}_7512_batch.zip"


def safe_pdf_output_name(source_name: str, index: int, used_names: set[str]) -> str:
    basename = source_name.replace("\\", "/").rsplit("/", 1)[-1]
    source_stem = Path(basename).stem
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", source_stem).strip("._-")
    if not safe_stem:
        safe_stem = f"document_{index:02d}"

    output_name = f"{safe_stem}_edited_7512.pdf"
    if output_name.casefold() in used_names:
        output_name = f"{safe_stem}_edited_7512_{index:02d}.pdf"
    suffix = 2
    while output_name.casefold() in used_names:
        output_name = f"{safe_stem}_edited_7512_{index:02d}_{suffix}.pdf"
        suffix += 1
    used_names.add(output_name.casefold())
    return output_name


def load_client_consignee_mapping() -> dict[str, dict[str, list[str]]]:
    mapping_path = Path(__file__).with_name("client_consignees.json")
    try:
        raw_mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProcessingError("The client and consignee mapping file could not be loaded.") from exc

    mapping: dict[str, dict[str, list[str]]] = {}
    if not isinstance(raw_mapping, dict):
        raise ProcessingError("The client and consignee mapping file has an invalid format.")

    for raw_client, raw_destinations in raw_mapping.items():
        client = str(raw_client).strip()
        if not client or not isinstance(raw_destinations, dict):
            continue
        destinations: dict[str, list[str]] = {}
        for raw_code, raw_consignees in raw_destinations.items():
            code = str(raw_code).strip().upper()
            if re.fullmatch(r"[A-Z]{3}", code) and isinstance(raw_consignees, list):
                choices = [str(value).strip() for value in raw_consignees if str(value).strip()]
                if choices:
                    destinations[code] = choices
        if destinations:
            mapping[client] = destinations
    return mapping


def _uppercase_destination_code() -> None:
    st.session_state.destination_code = st.session_state.destination_code.strip().upper()


def _reset_destination_for_client_change() -> None:
    st.session_state.destination_code = ""
    for key in list(st.session_state.keys()):
        if key.startswith("consignee_"):
            del st.session_state[key]


def _parse_positive_decimal(value: str, label: str) -> Decimal:
    try:
        number = Decimal(value.replace(",", "").strip())
    except (InvalidOperation, AttributeError) as exc:
        raise ProcessingError(f"Enter a valid {label}.") from exc
    if not number.is_finite() or number <= 0:
        raise ProcessingError(f"{label} must be greater than zero.")
    return number


def main() -> None:
    st.set_page_config(page_title="CBP 7512 PDF Editor", page_icon="📄", layout="wide")
    st.title("CBP Form 7512 PDF Editor")
    st.caption("Upload the original form, enter the shipment details, and download the edited PDF. PDF内容只在本次会话内存中处理。")

    try:
        client_consignee_mapping = load_client_consignee_mapping()
    except ProcessingError as exc:
        st.error(str(exc))
        st.stop()

    uploaded_pdfs = st.file_uploader(
        "Original CBP Form 7512 PDFs",
        type=["pdf"],
        accept_multiple_files=True,
    )
    st.caption("Select multiple PDFs. The same shipment details will be applied to every file; multiple results are packaged in one ZIP download.")
    st.subheader("Client, destination and consignee")
    client_choice = st.selectbox(
        "Client *",
        options=["-- Select a Client --", *client_consignee_mapping.keys()],
        key="client_choice",
        on_change=_reset_destination_for_client_change,
    )
    client_selected = client_choice in client_consignee_mapping
    client_destinations = client_consignee_mapping.get(client_choice, {})
    code_input = st.text_input(
        "Three-character destination code *",
        max_chars=3,
        placeholder="e.g. SAP",
        key="destination_code",
        on_change=_uppercase_destination_code,
        disabled=not client_selected,
    )
    destination_code = code_input.strip().upper()
    consignee_options = client_destinations.get(destination_code, [])
    valid_destination = client_selected and bool(re.fullmatch(r"[A-Z]{3}", destination_code)) and bool(consignee_options)
    if valid_destination:
        consignee_choices = ["-- Select a Consignee --", *consignee_options]
    elif client_selected:
        consignee_choices = ["-- Enter a valid destination code first --"]
    else:
        consignee_choices = ["-- Select a client first --"]
    consignee_choice = st.selectbox(
        "Consignee *",
        options=consignee_choices,
        key=f"consignee_{client_choice}_{destination_code or 'empty'}",
        disabled=not valid_destination,
    )
    if client_selected:
        st.caption(f"Available destinations: {', '.join(client_destinations)}")
    if destination_code and client_selected and not valid_destination:
        st.info("Enter a three-character destination code available for the selected client.")

    with st.form("form_7512_values", clear_on_submit=False):
        st.subheader("Fields to add")
        left, right = st.columns(2)
        with left:
            export_awb = st.text_input("1. Export AWB # *", placeholder="e.g. 369-11000006")
            port_code = st.selectbox(
                "4. Foreign port of lading *",
                options=("", "CN", "HK"),
                format_func=lambda code: "-- Select CN or HK --" if not code else f"{code} - {PORT_CHOICES[code]}",
            )
            number_of_packages = st.text_input("6. Number of packages *", placeholder="e.g. 100")
        with right:
            gross_weight = st.text_input("7. Gross weight (KG) *", placeholder="e.g. 125.5")
            value = st.text_input("8. Value ($) *", placeholder="e.g. 100.00")
        st.caption("Fixed fields: #3 Flag = US; #5 Description = SHOES, FOOTWEAR WOMEN'S DRESSES MEN'S SHIRTS")
        submitted = st.form_submit_button("Process all PDFs", type="primary", use_container_width=True)

    if submitted:
        if not uploaded_pdfs:
            st.error("Upload at least one CBP Form 7512 PDF first.")
        elif not client_selected:
            st.error("Choose a client.")
        elif not export_awb.strip():
            st.error("Export AWB # is required.")
        elif not valid_destination:
            st.error("Enter a valid three-character destination code for the selected client.")
        elif consignee_choice == "-- Select a Consignee --":
            st.error("Choose a Consignee for the destination code.")
        elif not port_code:
            st.error("Choose CN or HK for the foreign port of lading.")
        else:
            try:
                packages_number = _parse_positive_decimal(number_of_packages, "number of packages")
                if packages_number != packages_number.to_integral_value():
                    raise ProcessingError("Number of packages must be a whole number.")
                weight_number = _parse_positive_decimal(gross_weight, "gross weight")
                value_number = _parse_positive_decimal(value, "value")
                values = {
                    "export_awb": export_awb.strip(),
                    "consignee": consignee_choice,
                    "foreign_port": PORT_CHOICES[port_code],
                    "number_of_packages": f"{int(packages_number):,} PKG",
                    "gross_weight": f"{format(weight_number.normalize(), 'f')} KG",
                    "value": f"${format(value_number, '.2f')}",
                }
                archive_name = safe_archive_name(export_awb)
            except ProcessingError as exc:
                st.error(str(exc))
            else:
                processed_files: list[tuple[str, str, bytes]] = []
                processing_errors: list[tuple[str, str]] = []
                used_names: set[str] = set()

                for index, uploaded_pdf in enumerate(uploaded_pdfs, start=1):
                    try:
                        output_bytes = process_pdf(uploaded_pdf.getvalue(), values)
                        output_name = safe_pdf_output_name(uploaded_pdf.name, index, used_names)
                        processed_files.append((uploaded_pdf.name, output_name, output_bytes))
                    except ProcessingError as exc:
                        processing_errors.append((uploaded_pdf.name, str(exc)))
                    except Exception:
                        processing_errors.append(
                            (uploaded_pdf.name, "PDF processing failed. Confirm that it is a clean, one-page CBP Form 7512 PDF and try again.")
                        )

                if processing_errors:
                    st.warning(f"{len(processing_errors)} of {len(uploaded_pdfs)} file(s) could not be processed.")
                    for source_name, message in processing_errors:
                        st.error(f"{source_name}: {message}")

                if processed_files:
                    st.success(f"Processed {len(processed_files)} of {len(uploaded_pdfs)} PDF file(s).")
                    if len(uploaded_pdfs) == 1 and len(processed_files) == 1:
                        _, output_name, output_bytes = processed_files[0]
                        st.download_button(
                            "Download edited PDF",
                            data=output_bytes,
                            file_name=output_name,
                            mime="application/pdf",
                            use_container_width=True,
                        )
                    else:
                        archive = io.BytesIO()
                        with zipfile.ZipFile(archive, mode="w", compression=zipfile.ZIP_DEFLATED) as zip_file:
                            for _, output_name, output_bytes in processed_files:
                                zip_file.writestr(output_name, output_bytes)
                        st.download_button(
                            f"Download {len(processed_files)} edited PDF(s) (ZIP)",
                            data=archive.getvalue(),
                            file_name=archive_name,
                            mime="application/zip",
                            use_container_width=True,
                        )
                        with st.expander("Processed files"):
                            for source_name, output_name, _ in processed_files:
                                st.write(f"{source_name} → {output_name}")

    with st.expander("Field placement guide"):
        st.markdown(
            "The app follows the green numbered markers in the supplied instruction PDF. "
            "#1 Export AWB # is placed over the red value in Car number and initial. #2 Consignee options are filtered by client and three-character destination code. "
            "The entire original Consignee field is cleared before new text is added. Consignee text uses a fixed 7 pt font and is truncated with an ellipsis if it exceeds two lines. "
            "#3 is fixed to US; #4 maps CN/HK to the specified port text and copies it into Last foreign port; #5 is the fixed description; #6-8 use the entered package count, gross weight, and value. "
            "The existing B/L No. and Exported from row are preserved. The page is flattened at 300 dpi to remove old content, so form text in the output is not selectable."
        )


if __name__ == "__main__":
    main()
