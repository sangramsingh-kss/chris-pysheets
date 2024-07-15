try:
    import constants
except:
    from static import constants
import functools
import json
import sys

cache = functools.cache if hasattr(functools, "cache") else lambda func: func


def encode(model):
    buffer = []
    model.encode(buffer)
    return "\n".join(buffer)


def decode(json_string, env={}):
    try:
        model_dict = json.loads(json_string)
    except:
        print("Corrupt json:")
        for n, line in enumerate(json_string.split("\n")):
            print(f"{n+1:5d}", line)
        raise
    return convert(model_dict, env)


def convert(model_dict, env={}):
    if "_listeners" in model_dict:
        del model_dict["_listeners"]
    class_name = model_dict.get("_class", "Cell")
    if "_class" in model_dict:
        del model_dict["_class"]
    clazz = globals()[class_name] if class_name in globals() else env[class_name]
    return clazz(**model_dict)


def get_sheet(data, uid=None):
    try:
        return decode(data) if data else Sheet(uid=uid)
    except Exception as e:
        print("Could not load data", e)
        for n,line in enumerate(data.split("\n"), 1):
            print(n, line)
        raise e


@cache
def get_col_row_from_key(key):
    row = 0
    col = 0
    for c in key:
        if c.isdigit():
            row = row * 10 + int(c)
        else:
            col = col * 26 + ord(c) - ord("A") + 1
    return col, row


@cache
def get_column_name(col):
    parts = []
    while col > 0:
        col, remainder = divmod(col - 1, 26)
        parts.insert(0, chr(remainder + ord("A")))
    return "".join(parts)


@cache
def get_key_from_col_row(col, row):
    return f"{get_column_name(col)}{row}"


class Model(dict):
    def __init__(self):
        super().__init__()
        self._listeners = []
        self._class = self.__class__.__name__

    def listen(self, callback):
        self._listeners.append(callback)

    def notify(self, listener, info):
        if "ltk" in sys.modules:
            import ltk # we are running in PyScript
            ltk.schedule(lambda: listener(self, info), f"notify for {id(self)}", 0)
        else:
            listener(self, info) # we are running in the server or as unit test

    def __setattr__(self, name: str, value):
        old_value = getattr(self, name, None)
        if old_value == value:
            return
        object.__setattr__(self, name, value)
        self[name] = value
        if not name.startswith("_"):
            self.notify_listeners({ "name": name })
    
    def notify_listeners(self, info):
        for listener in self._listeners:
            self.notify(listener, info)
    
    def encode(self, buffer: list):
        buffer.append("{")
        self.encode_fields(buffer)
        buffer.append("}")
    
    def encode_fields(self, buffer: list):
        raise NotImplementedError(f"{self.__class__.__name__} is missing encode_fields")




class Sheet(Model):
    def __init__(self, uid="", name="Untitled Sheet",
                 columns=None, rows=None, cells=None, previews=None,
                 selected="A1", screenshot="/screenshot.png",
                 created_timestamp=0, updated_timestamp=0, column_count=26, row_count=50,
                 _class="Sheet"):
        super().__init__()
        self.uid = uid
        self.name = name
        self.columns = {} if columns is None else columns
        self.rows = {} if rows is None else rows
        self.cells = self.convert_cells({} if cells is None else cells)
        self.previews = self.convert_previews({} if previews is None else previews)
        self.selected = selected
        self.screenshot = screenshot
        self.created_timestamp = created_timestamp
        self.updated_timestamp = updated_timestamp
        self.column_count = column_count
        self.row_count = row_count
        
    def convert_cells(self, cells):
        for key, cell_dict in cells.items():
            if not isinstance(cell_dict, Cell):
                cells[key] = Cell(**cell_dict)
        return cells

    def encode_fields(self, buffer: list):
        self.encode_cells(buffer)
        self.encode_previews(buffer)
        buffer.append(f'"created_timestamp":{json.dumps(self.created_timestamp)},')
        buffer.append(f'"updated_timestamp":{json.dumps(self.updated_timestamp)},')
        buffer.append(f'"rows":{json.dumps(self.rows)},')
        buffer.append(f'"columns":{json.dumps(self.columns)},')
        buffer.append(f'"row_count":{json.dumps(self.row_count)},')
        buffer.append(f'"column_count":{json.dumps(self.column_count)},')
        buffer.append(f'"screenshot":{json.dumps(self.screenshot)},')
        buffer.append(f'"selected":{json.dumps(self.selected)},')
        buffer.append(f'"uid":{json.dumps(self.uid)},')
        buffer.append(f'"_class":"Sheet",')
        buffer.append(f'"name":{json.dumps(self.name)}')

    def encode_cells(self, buffer: list):
        buffer.append('"cells":{')
        needs_comma = False
        for cell in self.cells.values():
            if isinstance(cell, str) or cell.script == "" and cell.value == "":
                continue
            buffer.append(f"{',' if needs_comma else ''}{json.dumps(cell.key)}:")
            buffer.append("{")
            cell.encode_fields(buffer)
            buffer.append("}")
            needs_comma = True
        buffer.append('},')

    def encode_previews(self, buffer: list):
        buffer.append('"previews":{')
        needs_comma = False
        for preview in self.previews.values():
            buffer.append(f"{',' if needs_comma else ''}{json.dumps(preview.key)}:")
            buffer.append("{")
            preview.encode_fields(buffer)
            buffer.append("}")
            needs_comma = True
        buffer.append('},')

    def convert_previews(self, previews):
        self.previews = {}
        for key, preview_dict in previews.items():
            previews[key] = self.get_preview(**preview_dict)
        return previews

    def get_cell_keys(self, from_col, to_col, from_row, to_row):
        keys = []
        for col in range(from_col, to_col + 1):
            for row in range(from_row, to_row + 1):
                keys.append(get_key_from_col_row(col, row))
        return keys

    def get_cell(self, key):
        if not key in self.cells:
            cell = Cell(key=key)
            self.cells[key] = cell
            self.row_count = max(self.row_count, cell.row)
            self.column_count = max(self.column_count, cell.column)
        return self.cells[key]

    def get_preview(self, key, **args):
        if not key in self.previews:
            self.previews[key] = Preview(key, **args)
        return self.previews[key]

    def __eq__(self, other):
        return isinstance(other, Sheet) and other.uid == self.uid


class Preview(Model):
    def __init__(self, key, html="", embed=False, left=0, top=0, width=0, height=0):
        super().__init__()
        self.key = key
        self.html = html
        self.embed = embed
        self.left = left
        self.top = top
        self.width = width
        self.height = height

    def encode_fields(self, buffer: list):
        buffer.append(f'"html":{json.dumps(self.html)},')
        buffer.append(f'"embed":{json.dumps(self.embed)},')
        buffer.append(f'"left":{json.dumps(self.left)},')
        buffer.append(f'"top":{json.dumps(self.top)},')
        buffer.append(f'"width":{json.dumps(self.width)},')
        buffer.append(f'"height":{json.dumps(self.height)},')
        buffer.append(f'"key":{json.dumps(self.key)}')


class Cell(Model):
    def __init__(self, key="", column=0, row=0, value="", script="", style=None, embed=None, _class="Cell"):
        super().__init__()
        self.key = key
        if not row or not column:
            column, row = get_col_row_from_key(key)
        self.column = column
        self.row = row
        self.value = value
        self.script = script or value
        self.style = {} if style is None else style

    def encode_fields(self, buffer: list):
        if self.value not in ["", self.script]:
            buffer.append(f'"value":{json.dumps(self.value)},')
        buffer.append(f'"script":{json.dumps(self.script)},')
        self.encode_style(buffer)
        buffer.append(f'"key":{json.dumps(self.key)}')

    def encode_style(self, buffer: list):
        styles = []
        for property, value in self.style.items():
            if value != constants.DEFAULT_STYLE.get(property):
                styles.append(f'{json.dumps(property)}:{json.dumps(value)}')
        if styles:
            buffer.append('"style":{')
            buffer.append(f'{",".join(styles)}')
            buffer.append('},')

    def clear(self):
        self.script = ""
        self.value = ""
        self.style = {}


class Edit(Model):
    def apply(self, sheet):
        raise NotImplementedError(f"{self.__class__.__name__}.apply")

    def undo(self, sheet):
        raise NotImplementedError(f"{self.__class__.__name__}.undo")


class NameChanged(Edit):
    def __init__(self, _name="", name=""):
        super().__init__()
        self._name = _name
        self.name = name

    def apply(self, sheet: Sheet):
        sheet.name = self.name

    def undo(self, sheet: Sheet):
        sheet.name = self._name
        return True


class SelectionChanged(Edit):
    def __init__(self, key=""):
        super().__init__()
        self.key = key

    def apply(self, sheet: Sheet):
        sheet.selected = self.key
        
    def undo(self, sheet: Sheet):
        return False


class ScreenshotChanged(Edit):
    def __init__(self, url=""):
        super().__init__()
        self.url = url

    def apply(self, sheet: Sheet):
        sheet.screenshot = self.url


class ColumnChanged(Edit):
    def __init__(self, column: int=0, width: int=0):
        super().__init__()
        self.column = column
        self.width = width

    def apply(self, sheet: Sheet):
        sheet.columns[self.column] = self.width
        sheet.notify_listeners({ "name": "columns", "column": self.column, "width": self.width })


class RowChanged(Edit):
    def __init__(self, row=0, height=0):
        super().__init__()
        self.row = row
        self.height = height

    def apply(self, sheet: Sheet):
        sheet.rows[self.row] = self.height
        sheet.notify_listeners({ "name": "rows", "row": self.row, "height": self.height })


class CellChanged(Edit):
    def apply(self, sheet: Sheet):
        cell = sheet.get_cell(self.key)
        for key, value in self.__dict__.items():
            if not key.startswith("_"):
                setattr(cell, key, value)
    
    def undo(self, sheet: Sheet):
        cell = sheet.get_cell(self.key)
        for key, value in self.__dict__.items():
            if key.startswith("_"):
                setattr(cell, key[1:], value)
        return True


class CellValueChanged(CellChanged):
    def __init__(self, key="", _value="", value=""):
        super().__init__()
        self.key = key
        self._value = _value
        self.value = value


class CellEmbedChanged(CellChanged):
    def __init__(self, key="", embed=""):
        super().__init__()
        self.key = key
        self.embed = embed


class CellScriptChanged(CellChanged):
    def __init__(self, key="", _script="", script=""):
        super().__init__()
        self.key = key
        self._script = _script
        self.script = script


class CellStyleChanged(CellChanged):
    def __init__(self, key="", _style={}, style={}):
        super().__init__()
        self.key = key
        assert isinstance(_style, dict), f"_style must be a dict, not {type(_style)}:{_style}"
        assert isinstance(style, dict), f"style must be a dict, not {type(style)}:{style}"
        self._style = _style
        self.style = style


class PreviewChanged(Edit):
    def apply(self, sheet: Sheet):
        preview = sheet.get_preview(self.key)
        for key, value in self.__dict__.items():
            if not key.startswith("_"):
                setattr(preview, key, value)

    def notify_listeners(self, info):
        for listener in self._listeners:
            self.notify(listener, info)

    def undo(self, sheet: Sheet):
        return False


class PreviewPositionChanged(PreviewChanged):
    def __init__(self, key="", left=0, top=0):
        super().__init__()
        self.key = key
        self.left = left
        self.top = top


class PreviewDimensionChanged(PreviewChanged):
    def __init__(self, key="", width=0, height=0):
        super().__init__()
        self.key = key
        self.width = width
        self.height = height


class PreviewValueChanged(PreviewChanged):
    def __init__(self, key="", html=0):
        super().__init__()
        self.key = key
        self.html = html


class PreviewDeleted(Edit):
    def __init__(self, key=""):
        super().__init__()
        self.key = key

    def apply(self, sheet: Sheet):
        if self.key in sheet.previews:
            del sheet.previews[self.key]

    def undo(self, sheet: Sheet):
        return False
