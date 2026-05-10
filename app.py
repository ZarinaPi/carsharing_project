from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from sqlalchemy.orm import joinedload, selectinload
from datetime import datetime 
from sqlalchemy.exc import IntegrityError

app = Flask(__name__)
CORS(app)  # Разрешить запросы из браузера

# Настройка базы данных (SQLite)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# МОДЕЛИ

class CarClass(db.Model):
    """Метакласс для иерархии классификатора (таблица car_classes)"""
    __tablename__ = 'car_classes'
    
    id_class = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    short_name = db.Column(db.String(50))
    base_ei = db.Column(db.Integer, db.ForeignKey('ei.id_ei'))  # Ссылка на таблицу ei
    main_class = db.Column(db.Integer, db.ForeignKey('car_classes.id_class'))  # Рефлексивная связь
    
    # Рефлексивная связь (родитель → потомки)
    parent = db.relationship('CarClass', 
                             backref=db.backref('children', lazy='select'),
                             remote_side=[id_class])
    
    def to_dict(self):
        return {
            'id_class': self.id_class,
            'name': self.name,
            'short_name': self.short_name,
            'base_ei': self.base_ei,
            'main_class': self.main_class
        }
    
    def check_cycle(self, new_parent_id):
        """Проверка на циклы при смене родителя"""
        if new_parent_id == self.id_class:
            return True
        current = CarClass.query.get(new_parent_id)
        while current:
            if current.id_class == self.id_class:
                return True
            current = current.parent
        return False
    
    def get_all_children(self):
        """Рекурсивно найти всех потомков"""
        result = list(self.children)
        for child in self.children:
            result.extend(child.get_all_children())
        return result
    
    def get_all_parents(self):
        """Найти всех предков"""
        result = []
        current = self.parent
        while current:
            result.append(current)
            current = current.parent
        return result


class Car(db.Model):
    "Конкретные автомобили (таблица cars)"
    __tablename__ = 'cars'
    
    id_car = db.Column(db.Integer, primary_key=True)
    short_name = db.Column(db.String(20), unique=True, nullable=False)
    id_class = db.Column(db.Integer, db.ForeignKey('car_classes.id_class'), nullable=False)
    
    car_class = db.relationship('CarClass', backref='cars')
    
    def to_dict(self):
        attrs = {a.enum.name: a.value_obj.value for a in self.attributes}
        
        return {
            'id_car': self.id_car,
            'short_name': self.short_name,
            'name': self.car_class.name,
            'id_class': self.id_class,
            'attributes': attrs
        }


class Unit(db.Model):
    """Единицы измерения (таблица ei)"""
    __tablename__ = 'ei'
    id_ei = db.Column(db.Integer, primary_key=True)
    short_name = db.Column(db.String(10), nullable=False, unique=True)
    name = db.Column(db.String(50), nullable=False)
    
    def to_dict(self):
        return {
            'id_ei': self.id_ei,
            'short_name': self.short_name,
            'name': self.name
        }

# МОДЕЛИ ПЕРЕЧИСЛЕНИЙ

class Enumeration(db.Model):
    "Справочник-перечисление (CHEM_CLASS)"
    __tablename__ = 'enumerations'
    id_enum = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    value_type = db.Column(db.String(20), default='string') # string, numeric, icon
    
    # Связи
    values = db.relationship('EnumValue', backref='enumeration', lazy='select', cascade='all, delete-orphan')
    linked_classes = db.relationship('ClassEnum', backref='enumeration', lazy='select')

    def to_dict(self):
        return {
            'id_enum': self.id_enum,
            'name': self.name,
            'description': self.description,
            'value_type': self.value_type
        }

class EnumValue(db.Model):
    "Значение перечисления (POS_ENUM)"
    __tablename__ = 'enum_values'
    id_value = db.Column(db.Integer, primary_key=True)
    id_enum = db.Column(db.Integer, db.ForeignKey('enumerations.id_enum'), nullable=False)
    value = db.Column(db.String(100), nullable=False)
    sort_order = db.Column(db.Integer, default=0) # NUM из PDF
    numeric_value = db.Column(db.Float)
    icon_url = db.Column(db.String(255))
    unit_id = db.Column(db.Integer, db.ForeignKey('ei.id_ei'))
    
    unit = db.relationship('Unit')
    
    def to_dict(self):
        return {
            'id_value': self.id_value,
            'value': self.value,
            'sort_order': self.sort_order,
            'numeric_value': self.numeric_value,
            'icon_url': self.icon_url,
            'unit': self.unit.to_dict() if self.unit else None
        }

class ClassEnum(db.Model):
    "Привязка перечисления к классу автомобилей"
    __tablename__ = 'class_enums'
    id_class = db.Column(db.Integer, db.ForeignKey('car_classes.id_class'), primary_key=True)
    id_enum = db.Column(db.Integer, db.ForeignKey('enumerations.id_enum'), primary_key=True)
    is_required = db.Column(db.Boolean, default=False)
    
    car_class = db.relationship('CarClass', backref=db.backref('linked_enums', lazy='select'))

class CarEnumValue(db.Model):
    "Выбранное значение характеристики у конкретной машины"
    __tablename__ = 'car_enum_values'
    id_car = db.Column(db.Integer, db.ForeignKey('cars.id_car'), primary_key=True)
    id_enum = db.Column(db.Integer, db.ForeignKey('enumerations.id_enum'), primary_key=True)
    id_value = db.Column(db.Integer, db.ForeignKey('enum_values.id_value'), nullable=False)
    
    car = db.relationship('Car', backref=db.backref('attributes', lazy='select'))
    enum = db.relationship('Enumeration')
    value_obj = db.relationship('EnumValue')
    
    def to_dict(self):
        return {
            'id_enum': self.id_enum,
            'enum_name': self.enum.name,
            'id_value': self.id_value,
            'value': self.value_obj.value,
            'sort_order': self.value_obj.sort_order
        }

# =============================================================================
# НОВЫЕ МОДЕЛИ ДЛЯ ГИБКИХ ПАРАМЕТРОВ ИЗДЕЛИЙ
# =============================================================================

class Parameter(db.Model):
    """
    Метакласс параметра: определяет тип, единицу измерения, описание.
    """
    __tablename__ = 'parameters'
    
    id_param = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False, index=True)  # "WIDTH", "WEIGHT"
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    
    # Тип значения: 'numeric', 'integer', 'string', 'datetime', 'enum'
    value_type = db.Column(db.String(20), nullable=False)  
    
    # Для числовых параметров: ссылка на единицу измерения (ei)
    unit_id = db.Column(db.Integer, db.ForeignKey('ei.id_ei'))
    unit = db.relationship('Unit', foreign_keys=[unit_id])
    
    # Для параметров-перечислений: ссылка на справочник
    enum_id = db.Column(db.Integer, db.ForeignKey('enumerations.id_enum'))
    enumeration = db.relationship('Enumeration', foreign_keys=[enum_id])
    
    def to_dict(self):
        return {
            'id_param': self.id_param,
            'code': self.code,
            'name': self.name,
            'description': self.description,
            'value_type': self.value_type,
            'unit': self.unit.to_dict() if self.unit else None,
            'enumeration': self.enumeration.to_dict() if self.enumeration else None
        }


class ClassParameter(db.Model):
    """
    Привязка параметра к классу изделий с настройками.
    Аналог таблицы PAR_CLASS из ТЗ.
    """
    __tablename__ = 'class_parameters'
    
    id_class = db.Column(db.Integer, db.ForeignKey('car_classes.id_class'), primary_key=True)
    id_param = db.Column(db.Integer, db.ForeignKey('parameters.id_param'), primary_key=True)
    
    is_required = db.Column(db.Boolean, default=False)
    sort_order = db.Column(db.Integer, default=0)  # Порядок отображения
    
    # Ограничения для числовых параметров
    min_value = db.Column(db.Float)
    max_value = db.Column(db.Float)
    
    id_group = db.Column(db.Integer, db.ForeignKey('parameter_groups.id_group'), nullable=True)

    # Связи
    car_class = db.relationship('CarClass', backref='linked_params')
    parameter = db.relationship('Parameter')
    group = db.relationship('ParameterGroup')  # ← не забудьте добавить эту связь!
    
    
    def to_dict(self):  # ← ТЕПЕРЬ ВНУТРИ КЛАССА
        return {
            'id_class': self.id_class,
            'id_param': self.id_param,
            'param_code': self.parameter.code if self.parameter else None,
            'param_name': self.parameter.name if self.parameter else None,
            'value_type': self.parameter.value_type if self.parameter else None,
            'is_required': self.is_required,
            'sort_order': self.sort_order,
            'min_value': self.min_value,
            'max_value': self.max_value,
            'id_group': self.id_group,
            'group_name': self.group.name if self.group else None,
            'unit': self.parameter.unit.to_dict() if self.parameter and self.parameter.unit else None
        }


class CarParameter(db.Model):
    """
    Значение параметра у конкретного изделия.
    Аналог таблицы PAR_PROD из ТЗ.
    Поддержка разных типов через отдельные поля.
    """
    __tablename__ = 'car_parameters'
    
    id_car = db.Column(db.Integer, db.ForeignKey('cars.id_car'), primary_key=True)
    id_param = db.Column(db.Integer, db.ForeignKey('parameters.id_param'), primary_key=True)
    
    # Поля для разных типов значений (заполняется только одно в зависимости от типа)
    val_r = db.Column(db.Float)           # VAL_R - вещественные числа
    val_int = db.Column(db.Integer)       # VAL_INT - целые числа
    val_str = db.Column(db.String(255))   # VAL_STR - строки
    val_datetime = db.Column(db.DateTime) # VAL_DATETIME - даты
    enum_val = db.Column(db.Integer, db.ForeignKey('enum_values.id_value'))  # ENUM_VAL - перечисления
    
    enum_value = db.relationship('EnumValue', foreign_keys=[enum_val])
    parameter = db.relationship('Parameter')
    
    def _get_value(self):
        """Вспомогательный метод: возвращает значение в нужном формате"""
        if not self.parameter:
            return None
        vt = self.parameter.value_type
        if vt == 'numeric':
            return self.val_r
        elif vt == 'integer':
            return self.val_int
        elif vt == 'string':
            return self.val_str
        elif vt == 'datetime':
            return self.val_datetime.isoformat() if self.val_datetime else None
        elif vt == 'enum' and self.enum_value:
            return self.enum_value.to_dict()
        return None
    
    def to_dict(self):
        return {
            'id_param': self.id_param,
            'code': self.parameter.code if self.parameter else None,
            'name': self.parameter.name if self.parameter else None,
            'value_type': self.parameter.value_type if self.parameter else None,
            'value': self._get_value(),
            'unit': self.parameter.unit.to_dict() if self.parameter and self.parameter.unit else None
        }


class ParameterGroup(db.Model):
    """Группа параметров (агрегат) для визуального объединения характеристик в карточке"""
    __tablename__ = 'parameter_groups'
    id_group = db.Column(db.Integer, primary_key=True)
    id_class = db.Column(db.Integer, db.ForeignKey('car_classes.id_class'), nullable=True)  # NULL = глобальная группа
    name = db.Column(db.String(100), nullable=False)
    sort_order = db.Column(db.Integer, default=0)

    car_class = db.relationship('CarClass', backref='parameter_groups')


# API ЭНДПОИНТЫ (Методы сервера)

@app.route('/api/class/add', methods=['POST'])
def add_class():
    """Добавить новый класс (вершину)"""
    data = request.json
    main_class = data.get('main_class')
    
    # Проверка на цикл (если указан родитель)
    if main_class:
        # Создаём временный объект для проверки
        temp = CarClass(id_class=-999, main_class=main_class)
        if temp.check_cycle(main_class):
            return jsonify({'error': 'Cycle detected!'}), 400
    
    new_class = CarClass(
        name=data['name'],
        short_name=data.get('short_name', ''),
        base_ei=data.get('base_ei'),
        main_class=main_class
    )
    db.session.add(new_class)
    db.session.commit()
    return jsonify({'status': 'created', 'id_class': new_class.id_class}), 201


@app.route('/api/class/<int:id_class>', methods=['DELETE'])
def delete_class(id_class):
    clazz = CarClass.query.options(joinedload(CarClass.children), joinedload(CarClass.parent)).get(id_class)
    if not clazz:
        return jsonify({'error': 'Class not found'}), 404

    new_parent_id = clazz.main_class
    cars_in_class = Car.query.filter_by(id_class=id_class).all()

    # Если у класса нет родителя
    if new_parent_id is None:
        if len(cars_in_class) > 0 or len(clazz.children)> 0:
            return jsonify({
                'error': 'Cannot delete root class that contains children or cars.'
            }), 400
        
        db.session.delete(clazz)
        db.session.commit()
        return jsonify({'status': 'deleted'}), 200

    # Переносим детей
    children = CarClass.query.filter_by(main_class=id_class).all()
    for child in children:
        child.main_class = new_parent_id

    # Переносим машины
    for car in cars_in_class:
        car.id_class = new_parent_id
        
    # Фиксируем изменения перед удалением
    db.session.flush()

    # Удаляем класс
    db.session.delete(clazz)
    
    try:
        db.session.commit()
        return jsonify({
            'status': 'deleted',
            'message': f'Class deleted. {len(children)} children and {len(cars_in_class)} cars moved to parent ID {new_parent_id}.'
        }), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@app.route('/api/class/<int:id_class>/move', methods=['PUT'])
def move_class(id_class):
    "Переместить класс (сменить родителя)"
    data = request.json
    new_parent_id = data.get('new_parent_id')
    
    clazz = CarClass.query.options(joinedload(CarClass.parent)).get(id_class)
    if not clazz:
        return jsonify({'error': 'Class not found'}), 404
    
    # Проверка на циклы
    if clazz.check_cycle(new_parent_id):
        return jsonify({'error': 'Cycle detected!'}), 400
    
    clazz.main_class = new_parent_id
    db.session.commit()
    return jsonify({'status': 'moved'}), 200


@app.route('/api/class/<int:id_class>/children', methods=['GET'])
def get_children(id_class):
    "Найти всех потомков класса"
    clazz = CarClass.query.options(joinedload(CarClass.parent)).get(id_class)
    if not clazz:
        return jsonify({'error': 'Class not found'}), 404
    
    all_children = clazz.get_all_children()
    return jsonify({
        'class': clazz.to_dict(),
        'children': [c.to_dict() for c in all_children]
    }), 200


@app.route('/api/class/<int:id_class>/parents', methods=['GET'])
def get_parents(id_class):
    "Найти всех родителей (предков) класса"
    clazz = CarClass.query.options(joinedload(CarClass.parent)).get(id_class)
    if not clazz:
        return jsonify({'error': 'Class not found'}), 404
    
    all_parents = clazz.get_all_parents()
    return jsonify({
        'class': clazz.to_dict(),
        'parents': [p.to_dict() for p in all_parents]
    }), 200


@app.route('/api/class/terminal', methods=['GET'])
def get_terminal_classes():
    "Найти все терминальные классы (листья дерева)"
    all_classes = CarClass.query.options(selectinload(CarClass.children)).all()
    terminal = [c for c in all_classes if not c.children]
    return jsonify({'terminal_classes': [c.to_dict() for c in terminal]}), 200


@app.route('/api/class/tree', methods=['GET'])
def get_tree():
    "Просмотреть всю структуру классификатора"
    roots = CarClass.query.filter_by(main_class=None).options(selectinload(CarClass.children)).all()
    
    def build_tree(node):
        return {
            'id_class': node.id_class,
            'name': node.name,
            'children': [build_tree(child) for child in node.children]
        }
    
    return jsonify({'tree': [build_tree(r) for r in roots]}), 200


@app.route('/api/car/add', methods=['POST'])
def add_car():
    data = request.json
    
    if not data or 'short_name' not in data or 'id_class' not in data:
        return jsonify({'error': 'Fields short_name and id_class are required'}), 400
    
    # Проверка существования класса
    if not CarClass.query.get(data['id_class']):
        return jsonify({'error': 'Class not found'}), 404

    new_car = Car(
        short_name=data['short_name'],
        id_class=data['id_class']
    )
    
    try:
        db.session.add(new_car)
        db.session.commit()
        return jsonify({'status': 'created', 'id_car': new_car.id_car}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/api/car/<int:id_car>', methods=['DELETE'])
def delete_car(id_car):
    "Удалить конкретный автомобиль"
    car = Car.query.get(id_car)
    if not car:
        return jsonify({'error': 'Car not found'}), 404
    
    db.session.delete(car)
    db.session.commit()
    return jsonify({'status': 'deleted'}), 200

@app.route('/api/car/<int:id_car>', methods=['PUT'])
def update_car(id_car):
    car = Car.query.get(id_car)
    if not car:
        return jsonify({'error': 'Car not found'}), 404
    
    data = request.json
    
    if 'id_class' in data: 
        target_class = CarClass.query.get(data['id_class'])
        if not target_class:
            return jsonify({'error': 'Target class does not exist'}), 404
        car.id_class = data['id_class']
    
    try:
        db.session.commit()
        return jsonify({'status': 'updated', 'car': car.to_dict()}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/api/cars', methods=['GET'])
def get_cars():
    "Получить список всех автомобилей"
    cars = Car.query.options(joinedload(Car.car_class)).all()
    return jsonify({'cars': [c.to_dict() for c in cars]}), 200


@app.route('/api/cars/<int:id_class>', methods=['GET'])
def get_cars_by_class(id_class):
    "Получить автомобили по классу (включая потомков)"
    clazz = CarClass.query.get(id_class)
    if not clazz:
        return jsonify({'error': 'Class not found'}), 404
    
    # Получить все потомков (включая сам класс)
    all_classes = [clazz] + clazz.get_all_children()
    class_ids = [c.id_class for c in all_classes]
    
    cars = Car.query.filter(Car.id_class.in_(class_ids)).options(joinedload(Car.car_class)).all()
    return jsonify({'cars': [c.to_dict() for c in cars]}), 200


# API ДЛЯ ПЕРЕЧИСЛЕНИЙ

#1. Управление самими перечислениями (справочниками)

@app.route('/api/enumeration/add', methods=['POST'])
def add_enumeration():
    """Создать новое перечисление (справочник)"""
    data = request.json
    
    if not data or 'name' not in data:
        return jsonify({'error': 'Field "name" is required'}), 400
    
    new_enum = Enumeration(
        name=data['name'],
        description=data.get('description', ''),
        value_type=data.get('value_type', 'string')  # 'string', 'numeric', 'icon'
    )
    
    try:
        db.session.add(new_enum)
        db.session.commit()
        return jsonify({'status': 'created', 'id_enum': new_enum.id_enum}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/api/enumerations', methods=['GET'])
def get_enumerations():
    """Получить список всех перечислений"""
    enums = Enumeration.query.all()
    return jsonify({'enumerations': [e.to_dict() for e in enums]}), 200

@app.route('/api/enumeration/<int:id_enum>', methods=['GET'])
def get_enumeration(id_enum):
    """Получить перечисление со всеми значениями"""
    enum = Enumeration.query.get(id_enum)
    if not enum:
        return jsonify({'error': 'Enumeration not found'}), 404
    
    # Получаем все значения, отсортированные по sort_order
    values = EnumValue.query.filter_by(id_enum=id_enum)\
                           .order_by(EnumValue.sort_order)\
                           .all()
    
    result = enum.to_dict()
    result['values'] = [v.to_dict() for v in values]
    return jsonify(result), 200

@app.route('/api/enumeration/<int:id_enum>', methods=['PUT'])
def update_enumeration(id_enum):
    """Редактировать перечисление"""
    enum = Enumeration.query.get(id_enum)
    if not enum:
        return jsonify({'error': 'Enumeration not found'}), 404
    
    data = request.json
    
    if 'name' in data:
        enum.name = data['name']
    if 'description' in data:
        enum.description = data['description']
    if 'value_type' in data:
        enum.value_type = data['value_type']
    
    try:
        db.session.commit()
        return jsonify({'status': 'updated', 'enumeration': enum.to_dict()}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/api/enumeration/<int:id_enum>', methods=['DELETE'])
def delete_enumeration(id_enum):
    "Удалить перечисление (вместе со значениями)"
    enum = Enumeration.query.get(id_enum)
    if not enum:
        return jsonify({'error': 'Enumeration not found'}), 404
    
    try:
        db.session.delete(enum)
        db.session.commit()
        return jsonify({'status': 'deleted'}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

#Управление значениями перечислений

@app.route('/api/enumeration/<int:id_enum>/value/add', methods=['POST'])
def add_enum_value(id_enum):
    "Добавить значение в перечисление"
    enum = Enumeration.query.get(id_enum)
    if not enum:
        return jsonify({'error': 'Enumeration not found'}), 404
    
    data = request.json
    
    if not data or 'value' not in data:
        return jsonify({'error': 'Field "value" is required'}), 400
    
    new_value = EnumValue(
        id_enum=id_enum,
        value=data['value'],
        sort_order=data.get('sort_order', 0),
        numeric_value=data.get('numeric_value'),
        icon_url=data.get('icon_url'),
        unit_id=data.get('unit_id')  # Ссылка на единицу измерения
    )
    
    try:
        db.session.add(new_value)
        db.session.commit()
        return jsonify({'status': 'created', 'id_value': new_value.id_value}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/api/enumeration/<int:id_enum>/values', methods=['GET'])
def get_enum_values(id_enum):
    "Получить все значения перечисления (отсортированные)"
    enum = Enumeration.query.get(id_enum)
    if not enum:
        return jsonify({'error': 'Enumeration not found'}), 404
    
    values = EnumValue.query.filter_by(id_enum=id_enum)\
                           .order_by(EnumValue.sort_order)\
                           .all()
    
    return jsonify({'values': [v.to_dict() for v in values]}), 200

@app.route('/api/enum-value/<int:id_value>', methods=['PUT'])
def update_enum_value(id_value):
    value = EnumValue.query.get(id_value)
    if not value:
        return jsonify({'error': 'Value not found'}), 404

    data = request.json

    if 'sort_order' in data:
        new_order = data['sort_order']
        id_enum = value.id_enum

        # Сдвигаем все значения этого справочника, которые >= нового порядка
        EnumValue.query.filter(
            EnumValue.id_enum == id_enum,
            EnumValue.sort_order >= new_order,
            EnumValue.id_value != id_value
        ).update({EnumValue.sort_order: EnumValue.sort_order + 1}, synchronize_session=False)

        value.sort_order = new_order
    else:
        # Обновляем остальные поля без сдвига
        if 'value' in data:
            value.value = data['value']
        if 'numeric_value' in data:
            value.numeric_value = data['numeric_value']
        if 'icon_url' in data:
            value.icon_url = data['icon_url']
        if 'unit_id' in data:
            value.unit_id = data['unit_id']

    try:
        db.session.commit()
        return jsonify({'status': 'updated', 'value': value.to_dict()}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/api/enum-value/<int:id_value>', methods=['DELETE'])
def delete_enum_value(id_value):
    """Удалить значение из перечисления"""
    value = EnumValue.query.get(id_value)
    if not value:
        return jsonify({'error': 'Value not found'}), 404
    
    try:
        db.session.delete(value)
        db.session.commit()
        return jsonify({'status': 'deleted'}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/api/class/<int:id_class>/enum/link', methods=['POST'])
def link_enum_to_class(id_class):
    "Привязать справочник к классу автомобилей"
    clazz = CarClass.query.get(id_class)
    if not clazz:
        return jsonify({'error': 'Class not found'}), 404

    data = request.json
    enumeration = Enumeration.query.get(data.get('id_enum'))
    if not enumeration:
        return jsonify({'error': 'Enumeration not found'}), 404

    # Проверка на дубликаты (нельзя привязать один справочник дважды)
    existing_link = ClassEnum.query.get((id_class, enumeration.id_enum))
    if existing_link:
        return jsonify({'error': 'Enumeration is already linked to this class'}), 409

    # Создаем связь
    # is_required - обязательно ли заполнять это поле (флаг из PDF)
    link = ClassEnum(
        id_class=id_class,
        id_enum=enumeration.id_enum,
        is_required=data.get('is_required', False)
    )
    db.session.add(link)
    db.session.commit()
    return jsonify({'status': 'linked', 'is_required': link.is_required}), 201

@app.route('/api/class/<int:id_class>/enums', methods=['GET'])
def get_class_enums(id_class):
    """Получить все доступные справочники для данного класса + наследование от родителей"""
    clazz = CarClass.query.get(id_class)
    if not clazz:
        return jsonify({'error': 'Class not found'}), 404

    # Собираем ВСЕ справочники: от самого класса + от всех родителей
    all_enums = {}  # Словарь для избежания дубликатов (ключ=id_enum)
    
    # Рекурсивная функция для сбора справочников по иерархии
    def collect_enums_from_class(cls):
        # 1. Добавляем справочники текущего класса
        for link in cls.linked_enums:
            if link.enumeration.id_enum not in all_enums:
                all_enums[link.enumeration.id_enum] = {
                    'enum': link.enumeration,
                    'is_required': link.is_required
                }
        
        # 2. Если есть родительский класс (main_class), идём вверх по иерархии
        if cls.main_class:
            parent = CarClass.query.get(cls.main_class)
            if parent:
                collect_enums_from_class(parent)
    
    # Запускаем сбор с текущего класса
    collect_enums_from_class(clazz)
    
    # 3. Формируем итоговый ответ
    result = []
    for enum_data in all_enums.values():
        enum = enum_data['enum']
        enum_dict = enum.to_dict()
        enum_dict['is_required'] = enum_data['is_required']
        
        # Получаем значения, отсортированные по sort_order
        values = EnumValue.query.filter_by(id_enum=enum.id_enum)\
                               .order_by(EnumValue.sort_order)\
                               .all()
        
        enum_dict['values'] = [v.to_dict() for v in values]
        result.append(enum_dict)
    
    return jsonify({'enums': result}), 200

@app.route('/api/car/<int:id_car>/attribute', methods=['PUT'])
def set_car_attribute(id_car):
    """Установить/изменить характеристику у конкретной машины (с учетом наследования)"""
    car = Car.query.get(id_car)
    if not car:
        return jsonify({'error': 'Car not found'}), 404

    data = request.json
    id_enum = data.get('id_enum')
    id_value = data.get('id_value')

    # Проверяем, привязан ли этот справочник к классу машины ИЛИ к любому из её родителей
    def is_enum_allowed_for_class(cls_id, enum_id):
        # Проверяем прямую привязку
        link = ClassEnum.query.get((cls_id, enum_id))
        if link:
            return True
        
        # Если нет, проверяем родителя (рекурсивно)
        clazz = CarClass.query.get(cls_id)
        if clazz and clazz.main_class:
            return is_enum_allowed_for_class(clazz.main_class, enum_id)
        
        return False

    if not is_enum_allowed_for_class(car.id_class, id_enum):
        return jsonify({'error': f'Enumeration {id_enum} is not allowed for this class'}), 400

    # Проверяем, существует ли такое значение в этом справочнике
    val = EnumValue.query.get(id_value)
    if not val or val.id_enum != id_enum:
        return jsonify({'error': f'Value {id_value} does not belong to enumeration {id_enum}'}), 400

    # Сохраняем или обновляем
    attribute = CarEnumValue.query.get((id_car, id_enum))
    
    if attribute:
        attribute.id_value = id_value
    else:
        attribute = CarEnumValue(id_car=id_car, id_enum=id_enum, id_value=id_value)
        db.session.add(attribute)

    try:
        db.session.commit()
        return jsonify({'status': 'updated', 'attribute': attribute.to_dict()}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@app.route('/api/car/<int:id_car>/attributes', methods=['GET'])
def get_car_attributes(id_car):
    """Получить все характеристики машины"""
    car = Car.query.get(id_car)
    if not car:
        return jsonify({'error': 'Car not found'}), 404

    attributes = CarEnumValue.query.filter_by(id_car=id_car).all()
    return jsonify({'attributes': [a.to_dict() for a in attributes]}), 200


# API ДЛЯ ЕДИНИЦ ИЗМЕРЕНИЯ (таблица ei)

@app.route('/api/units', methods=['GET'])
def get_units():
    """Получить все единицы измерения"""
    units = Unit.query.all()
    return jsonify({'units': [u.to_dict() for u in units]}), 200

@app.route('/api/unit/<int:id_ei>', methods=['GET'])
def get_unit(id_ei):
    """Получить единицу измерения по ID"""
    unit = Unit.query.get(id_ei)
    if not unit:
        return jsonify({'error': 'Unit not found'}), 404
    return jsonify(unit.to_dict()), 200

@app.route('/api/unit/add', methods=['POST'])
def add_unit():
    """Создать новую единицу измерения"""
    data = request.json
    
    if not data or 'short_name' not in data or 'name' not in data:
        return jsonify({'error': 'Fields short_name and name are required'}), 400
    
    # Проверка на дубликат сокращённого названия
    if Unit.query.filter_by(short_name=data['short_name']).first():
        return jsonify({'error': 'Unit with this short_name already exists'}), 409
        
    new_unit = Unit(short_name=data['short_name'], name=data['name'])
    try:
        db.session.add(new_unit)
        db.session.commit()
        return jsonify({'status': 'created', 'id_ei': new_unit.id_ei}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/api/unit/<int:id_ei>', methods=['PUT'])
def update_unit(id_ei):
    "Редактировать единицу измерения"
    unit = Unit.query.get(id_ei)
    if not unit:
        return jsonify({'error': 'Unit not found'}), 404
    
    data = request.json
    
    if 'short_name' in data:
        # Проверяем уникальность при изменении
        existing = Unit.query.filter(Unit.short_name == data['short_name'], Unit.id_ei != id_ei).first()
        if existing:
            return jsonify({'error': 'Short name already exists'}), 409
        unit.short_name = data['short_name']
        
    if 'name' in data:
        unit.name = data['name']
        
    try:
        db.session.commit()
        return jsonify({'status': 'updated', 'unit': unit.to_dict()}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/api/unit/<int:id_ei>', methods=['DELETE'])
def delete_unit(id_ei):
    "Удалить единицу измерения"
    unit = Unit.query.get(id_ei)
    if not unit:
        return jsonify({'error': 'Unit not found'}), 404
    
    try:
        db.session.delete(unit)
        db.session.commit()
        return jsonify({'status': 'deleted'}), 200
    except Exception as e:
        db.session.rollback()
        # Если на эту единицу ссылаются enum_values, SQLite вернёт ошибку FK
        return jsonify({'error': str(e)}), 500


# =============================================================================
# API ДЛЯ УПРАВЛЕНИЯ ПАРАМЕТРАМИ
# =============================================================================

@app.route('/api/parameter/add', methods=['POST'])
def add_parameter():
    """Создать новый параметр (метакласс)"""
    data = request.json
    
    if not data or 'code' not in data or 'name' not in data or 'value_type' not in data:
        return jsonify({'error': 'Fields code, name, value_type are required'}), 400
    
    valid_types = ['numeric', 'integer', 'string', 'datetime', 'enum']
    if data['value_type'] not in valid_types:
        return jsonify({'error': f'value_type must be one of {valid_types}'}), 400
    
    # Валидация: для типа 'enum' обязателен enum_id, для числовых - опционален unit_id
    if data['value_type'] == 'enum' and 'enum_id' not in data:
        return jsonify({'error': 'enum_id is required for enum type parameters'}), 400
    
    new_param = Parameter(
        code=data['code'],
        name=data['name'],
        description=data.get('description', ''),
        value_type=data['value_type'],
        unit_id=data.get('unit_id'),
        enum_id=data.get('enum_id')
    )
    
    try:
        db.session.add(new_param)
        db.session.commit()
        return jsonify({'status': 'created', 'id_param': new_param.id_param}), 201
    except Exception as e:
        db.session.rollback()
        if 'UNIQUE constraint' in str(e):
            return jsonify({'error': 'Parameter with this code already exists'}), 409
        return jsonify({'error': str(e)}), 500


@app.route('/api/parameters', methods=['GET'])
def get_parameters():
    """Получить список всех параметров"""
    params = Parameter.query.all()
    return jsonify({'parameters': [p.to_dict() for p in params]}), 200


@app.route('/api/parameter/<int:id_param>', methods=['GET'])
def get_parameter(id_param):
    """Получить параметр по ID"""
    param = Parameter.query.get(id_param)
    if not param:
        return jsonify({'error': 'Parameter not found'}), 404
    return jsonify(param.to_dict()), 200


@app.route('/api/parameter/<int:id_param>', methods=['PUT'])
def update_parameter(id_param):
    """Редактировать параметр"""
    param = Parameter.query.get(id_param)
    if not param:
        return jsonify({'error': 'Parameter not found'}), 404
    
    data = request.json
    if 'name' in data:
        param.name = data['name']
    if 'description' in data:
        param.description = data['description']
    # code и value_type менять опасно - требуют миграции данных
    
    try:
        db.session.commit()
        return jsonify({'status': 'updated', 'parameter': param.to_dict()}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@app.route('/api/parameter/<int:id_param>', methods=['DELETE'])
def delete_parameter(id_param):
    """Удалить параметр (если не используется)"""
    param = Parameter.query.get(id_param)
    if not param:
        return jsonify({'error': 'Parameter not found'}), 404
    
    # Проверка: используется ли параметр в классах или изделиях
    if ClassParameter.query.filter_by(id_param=param.id_param).first():
        return jsonify({'error': 'Cannot delete parameter that is linked to classes'}), 400
    
    try:
        db.session.delete(param)
        db.session.commit()
        return jsonify({'status': 'deleted'}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@app.route('/api/class/<int:id_class>/parameter/link', methods=['POST'])
def link_parameter_to_class(id_class):
    """Привязать параметр к классу изделий с настройками"""
    clazz = CarClass.query.get(id_class)
    if not clazz:
        return jsonify({'error': 'Class not found'}), 404

    data = request.json
    id_param = data.get('id_param')
    
    param = Parameter.query.get(id_param)
    if not param:
        return jsonify({'error': 'Parameter not found'}), 404

    # Проверка: не привязан ли уже этот параметр к классу
    existing = ClassParameter.query.get((id_class, id_param))
    if existing:
        return jsonify({'error': 'Parameter is already linked to this class'}), 409

    # Валидация ограничений для числовых типов
    min_val = data.get('min_value')
    max_val = data.get('max_value')
    
    if param.value_type in ('numeric', 'integer'):
        if min_val is not None and max_val is not None and min_val > max_val:
            return jsonify({'error': 'min_value cannot be greater than max_value'}), 400
    else:
        # Для не-числовых параметров ограничения не применяются
        min_val = max_val = None

    link = ClassParameter(
        id_class=id_class,
        id_param=id_param,
        is_required=data.get('is_required', False),
        sort_order=data.get('sort_order', 0),
        min_value=min_val,
        max_value=max_val
    )
    
    try:
        db.session.add(link)
        db.session.commit()
        return jsonify({'status': 'linked', 'link': link.to_dict()}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@app.route('/api/class/<int:id_class>/parameters', methods=['GET'])
def get_class_parameters(id_class):
    """
    Получить все параметры класса с учётом наследования от родителей.
    Возвращает параметры в порядке sort_order.
    """
    clazz = CarClass.query.get(id_class)
    if not clazz:
        return jsonify({'error': 'Class not found'}), 404

    # Словарь для сбора параметров (ключ=id_param), чтобы избежать дубликатов
    all_params = {}
    
    def collect_params_from_class(cls):
        """Рекурсивно собираем параметры от класса и его родителей"""
        # 1. Добавляем параметры текущего класса
        for link in cls.linked_params:
            if link.id_param not in all_params:
                all_params[link.id_param] = {
                    'link': link,
                    'defined_at_class': cls.id_class,
                    'defined_at_class_name': cls.name
                }
        
        # 2. Если есть родитель - идём вверх по иерархии
        if cls.main_class:
            parent = CarClass.query.get(cls.main_class)
            if parent:
                collect_params_from_class(parent)
    
    collect_params_from_class(clazz)
    
    # Формируем ответ: сортируем по sort_order, добавляем информацию о наследовании
    result = []
    for item in sorted(all_params.values(), key=lambda x: x['link'].sort_order):
        link = item['link']
        param_dict = link.parameter.to_dict()
        param_dict['is_required'] = link.is_required
        param_dict['sort_order'] = link.sort_order
        param_dict['min_value'] = link.min_value
        param_dict['max_value'] = link.max_value
        param_dict['inherited_from'] = {
            'id_class': item['defined_at_class'],
            'class_name': item['defined_at_class_name']
        } if item['defined_at_class'] != id_class else None
        result.append(param_dict)
    
    return jsonify({'parameters': result}), 200


@app.route('/api/class/<int:id_class>/group', methods=['POST'])
def create_parameter_group(id_class):
    """Создать новую группу параметров (агрегат) для класса"""
    clazz = CarClass.query.get(id_class)
    if not clazz:
        return jsonify({'error': 'Class not found'}), 404
    
    data = request.json
    if not data or 'name' not in data:
        return jsonify({'error': 'Field "name" is required'}), 400
    
    group = ParameterGroup(
        id_class=id_class,
        name=data['name'],
        sort_order=data.get('sort_order', 0)
    )
    try:
        db.session.add(group)
        db.session.commit()
        return jsonify({'status': 'created', 'id_group': group.id_group}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@app.route('/api/class/<int:id_class>/parameter/<int:id_param>/group', methods=['PUT'])
def assign_param_to_group(id_class, id_param):
    """Привязать параметр к группе (или открепить)"""
    link = ClassParameter.query.get((id_class, id_param))
    if not link:
        return jsonify({'error': 'Parameter is not linked to this class'}), 404
    
    data = request.json
    group_id = data.get('id_group')  # Передайте null, чтобы убрать из группы
    
    if group_id is not None:
        group = ParameterGroup.query.get(group_id)
        if not group:
            return jsonify({'error': 'Group not found'}), 404
        if group.id_class != id_class:
            return jsonify({'error': 'Group does not belong to this class'}), 400
            
    link.id_group = group_id
    db.session.commit()
    return jsonify({'status': 'updated'}), 200


@app.route('/api/class/<int:id_class>/parameters/grouped', methods=['GET'])
def get_class_parameters_grouped(id_class):
    """
    Получить параметры класса, сгруппированные по агрегатам.
    Возвращает структуру: {"groups": [...], "ungrouped": [...]}
    """
    clazz = CarClass.query.get(id_class)
    if not clazz:
        return jsonify({'error': 'Class not found'}), 404

    # Собираем параметры с учётом наследования (аналог get_class_parameters)
    all_params = {}
    def collect_params(cls):
        for link in cls.linked_params:
            if link.id_param not in all_params:
                all_params[link.id_param] = {'link': link, 'defined_at': cls.id_class}
        if cls.main_class:
            parent = CarClass.query.get(cls.main_class)
            if parent: collect_params(parent)
    collect_params(clazz)

    # Распределяем по группам
    groups = {}
    ungrouped = []
    
    for item in all_params.values():
        link = item['link']
        p_dict = link.to_dict()
        p_dict['inherited_from'] = item['defined_at'] if item['defined_at'] != id_class else None
        
        if link.id_group and link.group:
            gid = link.id_group
            if gid not in groups:
                groups[gid] = {
                    'id_group': gid,
                    'name': link.group.name,
                    'sort_order': link.group.sort_order,
                    'parameters': []
                }
            groups[gid]['parameters'].append(p_dict)
        else:
            ungrouped.append(p_dict)

    # Сортировка групп и параметров внутри
    sorted_groups = sorted(groups.values(), key=lambda x: x['sort_order'])
    for g in sorted_groups:
        g['parameters'].sort(key=lambda x: x['sort_order'])
    ungrouped.sort(key=lambda x: x['sort_order'])

    return jsonify({'groups': sorted_groups, 'ungrouped': ungrouped}), 200





@app.route('/api/car/<int:id_car>/parameter', methods=['PUT'])
def set_car_parameter(id_car):
    """Установить/изменить значение гибкого параметра для конкретного изделия"""
    car = Car.query.get(id_car)
    if not car:
        return jsonify({'error': 'Car not found'}), 404
    
    data = request.json
    if not data:
        return jsonify({'error': 'Request body is required'}), 400
    
    # Определяем параметр по коду или ID
    param = None
    if 'id_param' in data:
        param = Parameter.query.get(data['id_param'])
    elif 'param_code' in data:
        param = Parameter.query.filter_by(code=data['param_code']).first()
    
    if not param:
        return jsonify({'error': 'Parameter not found'}), 404
    
    # Проверяем, разрешён ли параметр для класса этого авто (с наследованием)
    def get_param_link(cls_id, param_id):
        link = ClassParameter.query.get((cls_id, param_id))
        if link:
            return link
        clazz = CarClass.query.get(cls_id)
        if clazz and clazz.main_class:
            return get_param_link(clazz.main_class, param_id)
        return None
    
    param_link = get_param_link(car.id_class, param.id_param)
    if not param_link:
        return jsonify({'error': f'Parameter "{param.code}" is not allowed for this class'}), 400
    
    value = data.get('value')
    enum_value_id = data.get('enum_value_id')
    
    # Валидация типа и значений
    err = _validate_and_convert_value(param, value, enum_value_id, param_link)
    if err:
        return jsonify({'error': err}), 400
    
    # Подготовка полей для сохранения
    val_r = val_int = val_str = val_datetime = enum_val = None
    if param.value_type == 'numeric':
        val_r = float(value)
    elif param.value_type == 'integer':
        val_int = int(value)
    elif param.value_type == 'string':
        val_str = str(value)
    elif param.value_type == 'datetime':
        val_datetime = datetime.fromisoformat(value.replace('Z', '+00:00'))
    elif param.value_type == 'enum':
        enum_val = enum_value_id
    
    # Upsert: обновляем или создаём
    car_param = CarParameter.query.get((id_car, param.id_param))
    if car_param:
        car_param.val_r, car_param.val_int, car_param.val_str = val_r, val_int, val_str
        car_param.val_datetime, car_param.enum_val = val_datetime, enum_val
    else:
        car_param = CarParameter(
            id_car=id_car, id_param=param.id_param,
            val_r=val_r, val_int=val_int, val_str=val_str,
            val_datetime=val_datetime, enum_val=enum_val
        )
        db.session.add(car_param)
    
    try:
        db.session.commit()
        return jsonify({'status': 'updated', 'parameter': car_param.to_dict()}), 200
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Invalid enum_value_id or FK constraint failed'}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


def _validate_and_convert_value(param, value, enum_value_id, param_link):
    """Валидация значения параметра согласно типу и ограничениям"""
    p_type = param.value_type
    
    if p_type == 'enum':
        if enum_value_id is None:
            return 'enum_value_id is required for enum parameters'
        ev = EnumValue.query.get(enum_value_id)
        if not ev or ev.id_enum != param.enum_id:
            return 'Invalid enum_value_id'
        return None
    
    if p_type in ('numeric', 'integer'):
        if value is None:
            return f'value is required for {p_type} parameter'
        try:
            num = float(value) if p_type == 'numeric' else int(value)
        except (ValueError, TypeError):
            return f'Invalid {p_type} value'
        if param_link.min_value is not None and num < param_link.min_value:
            return f'Value below minimum {param_link.min_value}'
        if param_link.max_value is not None and num > param_link.max_value:
            return f'Value exceeds maximum {param_link.max_value}'
        return None
    
    if p_type == 'string':
        if value is None:
            return 'value is required'
        # Примечание: для строк поле max_value интерпретируется как максимальная длина
        if param_link.max_value and len(str(value)) > param_link.max_value:
            return f'String too long (max {int(param_link.max_value)} chars)'
        return None
    
    if p_type == 'datetime':
        if value is None:
            return 'value is required'
        try:
            datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            return 'Invalid datetime format (use ISO 8601)'
        return None
    
    return f'Unsupported type: {p_type}'


@app.route('/api/cars/filter', methods=['POST'])
def filter_cars():
    """
    Отбор изделий по классу и значениям параметров.
    Возвращает список машин с полными характеристиками.
    """
    data = request.json
    if not data:
        return jsonify({'error': 'Request body is required'}), 400

    id_class = data.get('id_class')
    include_children = data.get('include_children', False)
    filters = data.get('filters', [])

    # 1. Определяем список ID классов для поиска
    target_class_ids = []
    if id_class:
        clazz = CarClass.query.get(id_class)
        if not clazz:
            return jsonify({'error': 'Class not found'}), 404
        target_class_ids = [clazz.id_class]
        if include_children:
            target_class_ids += [c.id_class for c in clazz.get_all_children()]

    # 2. Базовый пул машин по классу
    base_query = Car.query.filter(Car.id_class.in_(target_class_ids)) if target_class_ids else Car.query
    candidate_ids = set(car.id_car for car in base_query.all())

    # Если фильтров нет, сразу возвращаем результат
    if not filters:
        cars = Car.query.filter(Car.id_class.in_(target_class_ids)).options(joinedload(Car.car_class)).all()
        return jsonify({'cars': [_format_car_full(c) for c in cars], 'count': len(cars)}), 200

    # 3. Последовательное применение фильтров параметров (пересечение множеств)
    for f in filters:
        if not candidate_ids:
            break  # Оптимизация: если пул пуст, дальше искать нет смысла

        param = Parameter.query.filter_by(code=f.get('param_code')).first()
        if not param:
            return jsonify({'error': f'Parameter "{f.get("param_code")}" not found'}), 404

        op = f.get('op', '=')
        val = f.get('value')

        # Выбираем колонку в зависимости от типа параметра
        col = None
        if param.value_type in ('numeric', 'integer'):
            col = CarParameter.val_r if param.value_type == 'numeric' else CarParameter.val_int
        elif param.value_type == 'string':
            col = CarParameter.val_str
        elif param.value_type == 'datetime':
            col = CarParameter.val_datetime
        elif param.value_type == 'enum':
            col = CarParameter.enum_val

        if not col:
            continue

        # Строим подзапрос для поиска ID машин, удовлетворяющих фильтру
        q = db.session.query(CarParameter.id_car).filter(
            CarParameter.id_param == param.id_param,
            CarParameter.id_car.in_(candidate_ids)  # Ищем только среди оставшихся кандидатов
        )

        # Применяем оператор сравнения
        if op == '=': q = q.filter(col == val)
        elif op == '!=': q = q.filter(col != val)
        elif op == '>': q = q.filter(col > val)
        elif op == '<': q = q.filter(col < val)
        elif op == '>=': q = q.filter(col >= val)
        elif op == '<=': q = q.filter(col <= val)
        elif op == 'like': q = q.filter(col.like(f'%{val}%'))
        elif op == 'between' and isinstance(val, list) and len(val) == 2:
            q = q.filter(col.between(val[0], val[1]))

        candidate_ids &= set(row[0] for row in q.all())  # Пересечение

    # 4. Формируем итоговый ответ с полными данными
    final_cars = Car.query.filter(Car.id_car.in_(candidate_ids)).options(joinedload(Car.car_class)).all()
    return jsonify({'cars': [_format_car_full(c) for c in final_cars], 'count': len(final_cars)}), 200


def _format_car_full(car):
    """Вспомогательная функция: собирает карточку изделия со всеми параметрами"""
    # Базовые данные + перечисления (из вашего car.to_dict())
    result = car.to_dict()
    
    # Гибкие параметры (числа, строки, даты)
    flex_params = CarParameter.query.filter_by(id_car=car.id_car).all()
    result['parameters'] = [p.to_dict() for p in flex_params]
    return result


@app.route('/api/car/<int:id_car>/details', methods=['GET'])
def get_car_details(id_car):
    """
    Возвращает полную карточку изделия (аналог процедуры FIND_PAR_PROD).
    Включает: базовые данные, путь в классификаторе, значения перечислений,
    значения гибких параметров с единицами измерения и типами.
    """
    # Загружаем авто + его класс
    car = Car.query.options(joinedload(Car.car_class)).get(id_car)
    if not car:
        return jsonify({'error': 'Car not found'}), 404

    # 1. Формируем путь в классификаторе (Breadcrumbs)
    # get_all_parents() возвращает [родитель, дедушка, ..., корень]
    # Разворачиваем, чтобы получить [корень, ..., родитель, текущий_класс]
    parents = car.car_class.get_all_parents()[::-1]
    class_path = [p.to_dict() for p in parents] + [car.car_class.to_dict()]

    # 2. Собираем значения перечислений с полной информацией
    enum_attributes = CarEnumValue.query.filter_by(id_car=id_car).all()
    formatted_enums = []
    for attr in enum_attributes:
        formatted_enums.append({
            'id_enum': attr.id_enum,
            'enum_name': attr.enum.name,
            'value_id': attr.id_value,
            'value': attr.value_obj.value,
            'numeric_value': attr.value_obj.numeric_value,
            'icon_url': attr.value_obj.icon_url,
            'unit': attr.value_obj.unit.to_dict() if attr.value_obj.unit else None
        })

    # 3. Собираем гибкие параметры (числа, строки, даты)
    flex_params = CarParameter.query.filter_by(id_car=id_car).all()
    formatted_params = [p.to_dict() for p in flex_params]

    # 4. Формируем итоговый ответ
    return jsonify({
        'id_car': car.id_car,
        'short_name': car.short_name,
        'id_class': car.id_class,
        'class_name': car.car_class.name,
        'class_path': class_path,
        'enum_attributes': formatted_enums,
        'flexible_parameters': formatted_params
    }), 200

def _check_missing_required_params(id_car):
    """Возвращает список кодов обязательных параметров, которые не заполнены у изделия"""
    car = Car.query.get(id_car)
    if not car:
        return ["Car not found"]

    missing = []
    
    def collect_required_ids(cls_id, visited=None):
        if visited is None: visited = set()
        if cls_id in visited: return []
        visited.add(cls_id)
        
        clazz = CarClass.query.get(cls_id)
        if not clazz: return []
        
        req_ids = [link.id_param for link in clazz.linked_params if link.is_required]
        if clazz.main_class:
            req_ids += collect_required_ids(clazz.main_class, visited)
        return list(set(req_ids))

    required_ids = collect_required_ids(car.id_class)

    for pid in required_ids:
        param = Parameter.query.get(pid)
        if not param: continue

        cp = CarParameter.query.get((id_car, pid))
        is_filled = False
        if cp:
            vt = param.value_type
            if vt == 'numeric' and cp.val_r is not None: is_filled = True
            elif vt == 'integer' and cp.val_int is not None: is_filled = True
            elif vt == 'string' and cp.val_str not in (None, ''): is_filled = True
            elif vt == 'datetime' and cp.val_datetime is not None: is_filled = True
            elif vt == 'enum' and cp.enum_val is not None: is_filled = True

        if not is_filled:
            missing.append(param.code)

    return missing


@app.route('/api/car/<int:id_car>/validation/required', methods=['GET'])
def check_car_validation(id_car):
    """Проверить, заполнены ли все обязательные параметры для класса изделия"""
    missing = _check_missing_required_params(id_car)
    if missing:
        return jsonify({
            'status': 'invalid',
            'message': f'Required parameters are missing',
            'missing_required': missing
        }), 400
    return jsonify({'status': 'valid', 'message': 'All required parameters are filled'}), 200


@app.route('/api/car/<int:id_car>/parameters/batch', methods=['PUT'])
def batch_update_parameters(id_car):
    """
    Массовое обновление параметров изделия за один запрос.
    Атомарная операция: при ошибке валидации ни одно значение не сохраняется.
    """
    car = Car.query.get(id_car)
    if not car:
        return jsonify({'error': 'Car not found'}), 404

    data = request.json
    items = data.get('parameters', [])
    if not isinstance(items, list):
        return jsonify({'error': '"parameters" must be a list'}), 400

    # 1. Фаза валидации (собираем все изменения в памяти, но не пишем в БД)
    updates_to_apply = []
    validation_errors = []

    for item in items:
        try:
            # Определяем параметр
            param = None
            if 'param_code' in item:
                param = Parameter.query.filter_by(code=item['param_code']).first()
            elif 'id_param' in item:
                param = Parameter.query.get(item['id_param'])

            if not param:
                validation_errors.append({'item': item, 'error': 'Parameter not found'})
                continue

            # Проверка принадлежности к классу (с учётом наследования)
            temp_cls = car.id_class
            param_link = None
            while temp_cls:
                param_link = ClassParameter.query.get((temp_cls, param.id_param))
                if param_link: break
                c = CarClass.query.get(temp_cls)
                temp_cls = c.main_class if c else None

            if not param_link:
                validation_errors.append({'item': item, 'error': f'Parameter {param.code} not allowed for this class'})
                continue

            # Валидация значения (используем функцию из предыдущего шага)
            err = _validate_and_convert_value(param, item.get('value'), item.get('enum_value_id'), param_link)
            if err:
                validation_errors.append({'item': item, 'error': err})
                continue

            # Подготовка полей для записи
            vr, vi, vs, vd, ev = None, None, None, None, None
            if param.value_type == 'numeric': vr = float(item['value'])
            elif param.value_type == 'integer': vi = int(item['value'])
            elif param.value_type == 'string': vs = str(item['value'])
            elif param.value_type == 'datetime': vd = datetime.fromisoformat(str(item['value']).replace('Z', '+00:00'))
            elif param.value_type == 'enum': ev = item.get('enum_value_id')

            updates_to_apply.append((param.id_param, vr, vi, vs, vd, ev))

        except Exception as e:
            validation_errors.append({'item': item, 'error': str(e)})

    # Если есть ошибки валидации -> отклоняем весь пакет
    if validation_errors:
        return jsonify({'status': 'validation_failed', 'errors': validation_errors}), 400

    # 2. Фаза применения изменений (атомарно)
    try:
        for pid, vr, vi, vs, vd, ev in updates_to_apply:
            cp = CarParameter.query.get((id_car, pid))
            if cp:
                cp.val_r, cp.val_int, cp.val_str, cp.val_datetime, cp.enum_val = vr, vi, vs, vd, ev
            else:
                db.session.add(CarParameter(id_car=id_car, id_param=pid, val_r=vr, val_int=vi, val_str=vs, val_datetime=vd, enum_val=ev))

        db.session.commit()
        return jsonify({
            'status': 'success',
            'message': f'Successfully updated {len(updates_to_apply)} parameters',
            'updated_count': len(updates_to_apply)
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'db_error', 'error': str(e)}), 500


# ЗАПУСК СЕРВЕРА

if __name__ == '__main__':
    with app.app_context():
        db.create_all()  # Создать таблицы БД
        
        # Добавить корневой класс и единицу измерения, если нет
        if not Unit.query.first():
            db.session.add(Unit(short_name='шт', name='штуки'))
            db.session.commit()
        
        if not CarClass.query.first():
            root = CarClass(name='Каталог Каршеринга', short_name='ROOT')
            db.session.add(root)
            db.session.commit()
            print('База данных создана и заполнена тестовыми данными!')
    
    print('Сервер запущен на http://127.0.0.1:5000')
    app.run(debug=False, port=5000)