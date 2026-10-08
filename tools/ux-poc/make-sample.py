"""Generate an anonymous three-page PDF with CJK prose, math, and a textless figure.

Requires the developer's existing XeLaTeX, pdftoppm and Nanum Myeongjo font. This
recipe is an explicit developer command; the demo server never invokes TeX.
"""

import json
import subprocess
import tempfile
from pathlib import Path


def tex_text(value: str) -> str:
    """Escape authored prose as TeX text so it cannot introduce TeX commands."""
    replacements = {
        "\\": r"\textbackslash{}",
        "{": r"\{",
        "}": r"\}",
        "%": r"\%",
        "&": r"\&",
        "_": r"\_",
        "#": r"\#",
        "$": r"\$",
    }
    return "".join(replacements.get(character, character) for character in value)


def main() -> None:
    """Build a three-page PDF and PNGs in an owned temporary directory, retaining only assets."""
    directory = Path(__file__).resolve().parent
    reading = json.loads((directory / "native-reading.json").read_text(encoding="utf-8"))
    width, height = 210, 297
    nodes = [
        r"\node[anchor=north west,text width=178mm,inner sep=0pt,font=\fontsize{16}{23}\selectfont\bfseries] at ([xshift=16mm,yshift=-23mm]current page.north west){"
        + tex_text(reading["title"])
        + "};",
        r"\node[anchor=north west,font=\fontsize{9}{12}\selectfont] at ([xshift=16mm,yshift=-53mm]current page.north west){익명 연구자};",
    ]
    section_positions = {
        "intro": (0.076, 0.213),
        "methods": (0.076, 0.455),
        "results": (0.52, 0.213),
        "limits": (0.52, 0.752),
    }
    for index, section in enumerate(reading["sections"], 1):
        x, y = section_positions[section["id"]]
        nodes.append(
            r"\node[anchor=north west,inner sep=0pt,font=\fontsize{12}{16}\selectfont\bfseries] at ([xshift="
            + f"{x * width:.3f}mm,yshift=-{y * height:.3f}mm]current page.north west)"
            + "{\\pdfbookmark[1]{"
            + tex_text(section["label"].split(" ", 1)[1])
            + "}{section-"
            + str(index)
            + "}"
            + tex_text(section["label"])
            + "};"
        )
    for block in reading["blocks"]:
        rect = block["rect"]
        x, y, box_width = rect["x"] * width, rect["y"] * height, rect["w"] * width
        if block.get("kind") == "figure":
            nodes.extend(
                [
                    r"\draw[gray!35] ([xshift=109.2mm,yshift=-151.2mm]current page.north west) rectangle ++(84.8mm,-49mm);",
                    r"\node[anchor=west,font=\fontsize{9}{12}\selectfont] at ([xshift=113mm,yshift=-160mm]current page.north west){배치 A};",
                    r"\node[anchor=west,font=\fontsize{9}{12}\selectfont] at ([xshift=113mm,yshift=-177mm]current page.north west){배치 B};",
                    r"\fill[blue!35] ([xshift=135mm,yshift=-156mm]current page.north west) rectangle ++(48mm,-9mm);",
                    r"\fill[blue!65] ([xshift=135mm,yshift=-173mm]current page.north west) rectangle ++(36mm,-9mm);",
                ]
            )
            y = 204
        nodes.append(
            r"\node[anchor=north west,align=justify,inner sep=0pt,text width="
            + f"{box_width:.3f}mm,font=\\fontsize{{10.5}}{{15}}\\selectfont] at ([xshift={x:.3f}mm,yshift=-{y:.3f}mm]current page.north west)"
            + "{"
            + tex_text(block["text"])
            + "};"
        )
    document = (
        r"\documentclass[a4paper]{article}"
        "\n"
        r"\usepackage{fontspec}\setmainfont{Nanum Myeongjo}"
        "\n"
        r"\usepackage[margin=0pt]{geometry}\usepackage{tikz}\usepackage[unicode,hidelinks]{hyperref}"
        "\n"
        r"\pagestyle{empty}\begin{document}\null\begin{tikzpicture}[remember picture,overlay]"
        "\n"
        + "\n".join(nodes)
        + "\n"
        + r"\node[font=\fontsize{9}{12}\selectfont] at ([yshift=12mm]current page.south){1};"
        + "\n"
        + r"\end{tikzpicture}\newpage\null\begin{tikzpicture}[remember picture,overlay]"
        + "\n"
        + r"\node[anchor=north west,text width=178mm,inner sep=0pt,font=\fontsize{16}{23}\selectfont\bfseries] at ([xshift=16mm,yshift=-23mm]current page.north west){\pdfbookmark[1]{추가 비교}{additional}5 추가 비교};"
        + "\n"
        + r"\node[anchor=north west,text width=178mm,inner sep=0pt,font=\fontsize{11}{18}\selectfont] at ([xshift=16mm,yshift=-51mm]current page.north west){온도 응답은 운전기간과 함께 비교한다. 온도 차이를 한 쪽 안에서 반복해 읽고, 첫 쪽과 이 쪽의 검색 결과를 구분한다.};"
        + "\n"
        + r"\node[anchor=north west,text width=178mm,inner sep=0pt,font=\fontsize{11}{18}\selectfont] at ([xshift=16mm,yshift=-86mm]current page.north west){The thermal response depends on duration. A second thermal result tests repeated hits on the same page. Efficient flows and finite differences provide ordinary English extraction examples.};"
        + "\n"
        + r"\node[anchor=north west,text width=178mm,inner sep=0pt,font=\fontsize{11}{18}\selectfont] at ([xshift=16mm,yshift=-126mm]current page.north west){간단한 수식 예시: $\Delta T = \frac{Q}{mc}$, $\alpha + \beta = 1$. 수식의 시각적 순서와 복사한 텍스트의 순서는 별도로 확인한다.};"
        + "\n"
        + r"\node[font=\fontsize{9}{12}\selectfont] at ([yshift=12mm]current page.south){2};"
        + "\n"
        + r"\end{tikzpicture}\newpage\null\begin{tikzpicture}[remember picture,overlay]"
        + "\n"
        + r"\pdfbookmark[1]{텍스트 없는 그림}{textless}"
        + "\n"
        + r"\draw[gray!35,very thick] ([xshift=30mm,yshift=-50mm]current page.north west) rectangle ++(150mm,-145mm);"
        + "\n"
        + r"\fill[blue!35] ([xshift=45mm,yshift=-160mm]current page.north west) rectangle ++(30mm,70mm);"
        + "\n"
        + r"\fill[blue!65] ([xshift=90mm,yshift=-160mm]current page.north west) rectangle ++(30mm,90mm);"
        + "\n"
        + r"\fill[gray!55] ([xshift=135mm,yshift=-160mm]current page.north west) rectangle ++(30mm,45mm);"
        + "\n"
        + r"\end{tikzpicture}\end{document}"
        + "\n"
    )
    with tempfile.TemporaryDirectory(prefix="limn-native-sample-") as work:
        scratch = Path(work)
        (scratch / "sample.tex").write_text(document, encoding="utf-8")
        for _ in range(2):
            subprocess.run(
                ["xelatex", "-no-shell-escape", "-interaction=nonstopmode", "-halt-on-error", "sample.tex"],
                cwd=scratch,
                check=True,
                stdout=subprocess.DEVNULL,
            )
        for page in range(1, 4):
            name = "sample" if page == 1 else f"sample-{page}"
            subprocess.run(
                ["pdftoppm", "-f", str(page), "-singlefile", "-scale-to", "1123", "-png", "sample.pdf", name],
                cwd=scratch,
                check=True,
            )
            (directory / f"{name}.png").write_bytes((scratch / f"{name}.png").read_bytes())
        (directory / "sample.pdf").write_bytes((scratch / "sample.pdf").read_bytes())


if __name__ == "__main__":
    main()
