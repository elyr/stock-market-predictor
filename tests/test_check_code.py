"""The component layout check (scripts/check_code.py): it passes on the repository and catches each way to break the convention."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))
import check_code  # noqa: E402

SHORT = '\n'.join(f'<p>line {i}</p>' for i in range(10))
LONG = '\n'.join(f'<p>line {i}</p>' for i in range(check_code.TEMPLATE_LIMIT + 1))
EXACTLY_AT_LIMIT = '\n'.join(f'<p>line {i}</p>' for i in range(check_code.TEMPLATE_LIMIT))


def inline(template: str, styles: bool = True) -> str:
    style = "  styles: `\n    p { margin: 0; }\n  `,\n" if styles else ''
    return f"@Component({{\n  selector: 'app-x',\n  template: `\n{template}\n  `,\n{style}}})\nexport class X {{}}\n"


def split(url="./x.html", style="  styleUrl: './x.scss',\n", extra='') -> str:
    return f"@Component({{\n  selector: 'app-x',\n  templateUrl: '{url}',\n{style}{extra}}})\nexport class X {{}}\n"


def problems(tmp_path: Path, files: dict) -> list:
    for name, text in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
    return check_code.check_component_layout(tmp_path, list(files))


def test_repository_components_follow_the_layout():
    assert check_code.check_component_layout() == []
    # the check really looks at the components
    components = [f for f in check_code.tracked_files(f'{check_code.COMPONENT_DIR}/*') if f.endswith('.ts')]
    assert len(components) > 15


def test_short_inline_component_is_fine(tmp_path):
    assert problems(tmp_path, {'frontend/src/app/x.ts': inline(SHORT)}) == []


def test_template_at_the_limit_stays_inline(tmp_path):
    assert problems(tmp_path, {'frontend/src/app/x.ts': inline(EXACTLY_AT_LIMIT)}) == []


def test_long_inline_template_is_reported(tmp_path):
    found = problems(tmp_path, {'frontend/src/app/x.ts': inline(LONG)})
    assert len(found) == 1 and 'move it to x.html and its styles to x.scss' in found[0]


def test_long_template_in_files_is_fine(tmp_path):
    files = {'frontend/src/app/x.ts': split(), 'frontend/src/app/x.html': LONG, 'frontend/src/app/x.scss': 'p { margin: 0; }'}
    assert problems(tmp_path, files) == []


def test_short_template_in_a_file_is_reported(tmp_path):
    files = {'frontend/src/app/x.ts': split(), 'frontend/src/app/x.html': SHORT, 'frontend/src/app/x.scss': 'p {}'}
    found = problems(tmp_path, files)
    assert len(found) == 1 and 'is inline' in found[0]


def test_files_must_be_named_after_the_component(tmp_path):
    files = {'frontend/src/app/x.ts': split(url='./other.html', style="  styleUrl: './other.scss',\n"),
             'frontend/src/app/other.html': LONG, 'frontend/src/app/other.scss': 'p {}'}
    found = problems(tmp_path, files)
    assert any("templateUrl must be './x.html'" in p for p in found)
    assert any("styleUrl: './x.scss'" in p for p in found)


def test_template_file_needs_a_stylesheet_file_not_inline_styles(tmp_path):
    files = {'frontend/src/app/x.ts': split(style='', extra='  styles: `p {}`,\n'), 'frontend/src/app/x.html': LONG}
    found = problems(tmp_path, files)
    assert any("use styleUrl: './x.scss'" in p for p in found)
    assert any('styles belong in x.scss' in p for p in found)


def test_missing_files_are_reported(tmp_path):
    (tmp_path / 'frontend/src/app').mkdir(parents=True)
    (tmp_path / 'frontend/src/app/x.ts').write_text(split(), encoding='utf-8')
    found = check_code.check_component_layout(tmp_path, ['frontend/src/app/x.ts'])
    assert any('x.html does not exist' in p for p in found)
    assert any('x.scss does not exist' in p for p in found)


def test_inline_template_with_a_stylesheet_file_is_reported(tmp_path):
    text = inline(SHORT, styles=False).replace('  template:', "  styleUrl: './x.scss',\n  template:")
    found = problems(tmp_path, {'frontend/src/app/x.ts': text, 'frontend/src/app/x.scss': 'p {}'})
    assert any('inline template needs inline styles' in p for p in found)


def test_unused_template_and_style_files_are_reported(tmp_path):
    files = {'frontend/src/app/orphan.html': LONG, 'frontend/src/app/orphan.scss': 'p {}', 'frontend/src/styles.scss': 'p {}'}
    found = problems(tmp_path, files)
    assert len(found) == 2 and all('no component orphan.ts uses this file' in p for p in found)


def test_specs_and_plain_files_are_ignored(tmp_path):
    files = {'frontend/src/app/x.spec.ts': inline(LONG), 'frontend/src/app/format.ts': 'export const x = 1;\n'}
    assert problems(tmp_path, files) == []
