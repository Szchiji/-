from flask import Blueprint

# 定义蓝图，设置模板文件夹路径
cert_bp = Blueprint('certification', __name__, template_folder='templates', url_prefix='')

# 导入路由以生效
from . import routes
