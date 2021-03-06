from django.http import HttpRequest
from django.views import generic
from django.shortcuts import render, reverse, get_object_or_404, HttpResponseRedirect
from django.db.utils import IntegrityError

from .models import User, UserType, Goods
from .forms import (RegisterFEForm, RegisterBEForm, LoginFEForm, LoginBEForm, ChangeEmailForm, ChangePasswordFEForm,
                    ChangePasswordBEForm)
from .utils import APIResultBuilder

from django.views.decorators.csrf import csrf_exempt


def get_current_user(request):
    """获取当前用户对象"""

    try:
        user_id = request.session['user_id']
        user = User.objects.get(id=user_id)

        return user
    except (User.DoesNotExist, KeyError) as e:
        # 删除无效的用户登陆关联
        if type(e) is User.DoesNotExist:
            associate_user_to_client(request, None)

        return None


def associate_user_to_client(request, user_id):
    """关联用户登陆到客户端"""

    if user_id is None:
        request.session.flush()
    else:
        request.session['user_id'] = user_id


def redirect_to_index():
    """重定向到首页"""

    return HttpResponseRedirect(reverse('shop:goods_list'))


def user_auth(usertype, error_viewname=None):
    """用户授权管理修饰器

    可修饰以下种类的函数：
        - 一般视图函数，该函数的第一个参数用来接收 request 对象。
        - 视图类中的类似于 get() 和 post() 等的函数，这些函数会返回一个 HttpResponse 。

    Parameters
    ----------
    usertype: 允许访问指定视图的用户类型名称，该参数类型可以是 None 或 str 或它们的组成的列表和元组。
              用户类型名称为 None 代表未登录的访客。

    error_viewname: 当授权失败后需要跳转到的视图名称。默认为403错误视图。

    Examples
    --------
    @user_auth(usertype='admin')
    def logout_view(request):
        return ...

    @user_auth(usertype=['normal', 'seller', 'admin'], error_viewname='shop:center')
    def get(self, request, *args, **kwargs):
        return ...
    """

    if usertype is not None \
            and not isinstance(usertype, str) \
            and not isinstance(usertype, (list, tuple)):
        raise TypeError('parameter "usertype" must be None, str, list or tuple')

    def decorator(func):
        def wrapper(*args, **kwargs):
            # 检查参数
            try:
                first_arg = args[0]
            except IndexError:
                raise IndexError('first-parameter is not exist, The first-parameter must be django.views.View or '
                                 'django.http.HttpRequest')

            # 获取 request 对象
            if isinstance(first_arg, generic.View):
                request = first_arg.request
            elif isinstance(first_arg, HttpRequest):
                request = first_arg
            else:
                raise TypeError(f'{type(first_arg)} is not django.views.View or django.http.HttpRequest object, '
                                'The first-parameter must be django.views.View or django.http.HttpRequest')

            # 获取当前用户的类型
            current_user = get_current_user(request)
            current_usertype = current_user.type if current_user else None

            # 用户类型认证
            authorized = False
            if usertype is None:
                authorized = current_usertype is None
            elif isinstance(usertype, str):
                authorized = current_usertype == UserType.objects.get(typename=usertype)
            elif isinstance(usertype, (list, tuple)):
                auth_usertype = [UserType.objects.get(typename=t) if t else None for t in usertype]
                authorized = current_usertype in auth_usertype

            if authorized:
                return func(*args, **kwargs)
            elif error_viewname is None:
                return HttpResponseRedirect(reverse('shop:error_403'))
            else:
                return HttpResponseRedirect(reverse(error_viewname))

        return wrapper

    return decorator


class BasicUserView(generic.base.ContextMixin):
    """可提供用户信息的基本视图

    是所有需要使用用户信息的视图的基类。
    这并不是个直接可用的视图（至少目前是这样）。
    """

    def get_context_data(self, **kwargs):
        request = kwargs.pop('request')
        object_list = {
            # 添加当前用户context
            'current_user': get_current_user(request),
        }

        kwargs.update(object_list)
        return super().get_context_data(**kwargs)


class GoodsListView(generic.ListView, BasicUserView):
    """商品列表视图"""

    template_name = 'shop/goods_list.html'

    def get_queryset(self):
        queryset = Goods.objects.all()

        # 按商品关键词过滤
        if 'g' in self.request.GET:
            goods_kws = self.request.GET['g']
            queryset = queryset.filter(goods_name__contains=goods_kws)

        # 按商家ID过滤
        if 's' in self.request.GET:
            seller_id = self.request.GET['s']
            queryset = queryset.filter(seller_id=seller_id)

        return queryset

    def get_context_data(self, *, object_list=None, **kwargs):
        # 添加用户对象到 context
        object_list = super().get_context_data(request=self.request, kwargs=kwargs)

        # 添加搜索词到context
        if 'g' in self.request.GET:
            object_list['search_text'] = self.request.GET['g']

        # 添加商家到context
        if 's' in self.request.GET:
            object_list['seller'] = get_object_or_404(User, id=self.request.GET['s'])

        return object_list


class GoodsDetailView(generic.DetailView, BasicUserView):
    """商品详情视图"""

    model = Goods
    template_name = 'shop/goods_detail.html'

    def get_context_data(self, *, object_list=None, **kwargs):
        # 添加用户对象到 context
        object_list = super().get_context_data(request=self.request, **kwargs)

        # 添加商家到context
        object_list['seller'] = self.object.seller

        return object_list


class RegisterView(generic.FormView):
    """用户注册视图"""

    form_class = RegisterFEForm
    template_name = 'shop/register.html'

    @user_auth(usertype=None, error_viewname='shop:logout')
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    @user_auth(usertype=None, error_viewname='shop:logout')
    def post(self, request, *args, **kwargs):
        request_form = RegisterFEForm(request.POST)
        username = request_form['username'].value()
        email = request_form['email'].value()
        password1 = request_form['password'].value()
        password2 = request_form['password_again'].value()

        response_form = RegisterFEForm(dict(username=username, email=email))
        format_error_info = '注册信息格式错误'

        if not RegisterBEForm(request.POST).is_valid():
            # 表单格式错误
            for field in response_form.fields:
                response_form.add_error(field, format_error_info)
        elif User.objects.filter(username=username):
            # 该用户名已被使用
            response_form.add_error('username', '该用户名已被使用')
        elif User.objects.filter(email=email):
            # 该邮箱已被使用
            response_form.add_error('email', '该邮箱已被使用')
        elif password1 != password2:
            # 两次输入的密码不一致
            error_info = '两次输入的密码不一致'
            response_form.add_error('password', error_info)
            response_form.add_error('password_again', error_info)
        else:
            # 尝试新增用户
            try:
                user = User(username=username, email=email, password=password1)
                user.save()
                associate_user_to_client(request, user.id)

                return redirect_to_index()
            except IntegrityError:
                # 新增用户到数据库失败
                for field in response_form.fields:
                    response_form.add_error(field, format_error_info)

        return self.form_invalid(response_form)


class LoginView(generic.FormView):
    """用户登陆视图"""

    form_class = LoginFEForm
    template_name = 'shop/login.html'

    @user_auth(usertype=None, error_viewname='shop:logout')
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    @user_auth(usertype=None, error_viewname='shop:logout')
    def post(self, request, *args, **kwargs):
        request_form = LoginFEForm(request.POST)
        username = request_form['username'].value()
        password = request_form['password'].value()

        response_form = LoginFEForm(dict(username='', email=''))

        if not LoginBEForm(request.POST).is_valid():
            # 表单格式错误
            for field in response_form.fields:
                response_form.add_error(field, '注册信息格式错误')
        else:
            # 尝试登陆，检查用户名和密码
            try:
                user = User.objects.get(username=username)
                if not user.check_password(password):
                    raise User.DoesNotExist()

                associate_user_to_client(request, user.id)

                # 登陆成功
                return redirect_to_index()
            except User.DoesNotExist:
                # 用户名或密码错误
                error_info = '用户名或密码错误'
                response_form.add_error('username', error_info)
                response_form.add_error('password', error_info)

        return self.form_invalid(response_form)


def logout_view(request):
    """退出用户登陆视图"""

    associate_user_to_client(request, None)
    return HttpResponseRedirect(reverse('shop:login'))


class MemberInfoView(generic.TemplateView, BasicUserView):
    """个人中心视图"""

    template_name = 'shop/center/member_center/member_info.html'

    def get_context_data(self, **kwargs):
        # 添加用户对象到 context
        return super().get_context_data(request=self.request, kwargs=kwargs)

    @user_auth(usertype='normal')
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class ChangeMemberEmailView(generic.FormView, BasicUserView):
    """修改个人邮箱视图"""

    form_class = ChangeEmailForm
    template_name = 'shop/center/member_center/change_email.html'

    def get_context_data(self, **kwargs):
        # 添加用户对象到 context
        return super().get_context_data(request=self.request, kwargs=kwargs)

    @user_auth(usertype=['normal'])
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class ChangeMemberPasswordView(generic.FormView, BasicUserView):
    """修改个人密码视图"""

    form_class = ChangePasswordFEForm
    template_name = 'shop/center/member_center/change_password.html'

    def get_context_data(self, **kwargs):
        # 添加用户对象到 context
        return super().get_context_data(request=self.request, kwargs=kwargs)

    @user_auth(usertype=['normal'])
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


@user_auth(usertype=['normal', 'seller', 'admin'], error_viewname='shop:login')
def center_enter_view(request):
    """用户中心统一入口视图"""

    user = get_current_user(request)
    center_url = None

    # 判断用户类型并跳转到合适的用户中心
    if user is not None:
        if user.type == UserType.objects.get(typename='normal'):
            center_url = reverse('shop:member_info')
        elif user.typp == UserType.objects.get(typename='seller'):
            center_url = reverse('shop:member_info')
        elif user.type == UserType.objects.get(typename='admin'):
            center_url = reverse('shop:member_info')

    if center_url is not None:
        return HttpResponseRedirect(center_url)
    else:
        return redirect_to_index()


def error_403_view(request):
    """403错误视图"""

    return render(request, template_name='shop/error_403.html', status=403)


class APIView(generic.View):
    """API视图的基类"""
    # TODO: 缺少APIView的基本测试

    api_method_names = ['pull', 'create', 'update', 'delete']

    def __int__(self):
        self.result_builder = None
        super().__init__()

    @user_auth(usertype=['normal', 'seller', 'admin'], error_viewname='shop:api_unauthorized_error')
    @csrf_exempt
    def dispatch(self, request, *args, **kwargs):
        try:
            setattr(self, 'result_builder', APIResultBuilder())
            return super().dispatch(request, *args, **kwargs)
        except Exception:
            return HttpResponseRedirect(reverse('shop:api_server_error'))

    def get(self, request, *args, **kwargs):
        """推荐用于常规地获取对象"""

        return self.result_builder \
            .set_errors('Getting is not supported.') \
            .as_json_response(status=405)

    def post(self, request, *args, **kwargs):
        """不推荐直接实现此方法，请使用更具体的pull、create、update、delete方法"""

        if '_ext_method' in request.POST and request.POST['_ext_method'] in self.api_method_names:
            handler = getattr(self, request.POST['_ext_method'])
            return handler(request, *args, **kwargs)

        return self.result_builder \
            .set_errors('Failure to match the appropriate method.') \
            .as_json_response(status=405)

    def pull(self, request, *args, **kwargs):
        """推荐用于安全地获取对象"""

        return self.result_builder \
            .set_errors('Pulls is not supported.') \
            .as_json_response(status=405)

    def create(self, request, *args, **kwargs):
        """推荐用于创建对象（包括创建连接）"""

        return self.result_builder \
            .set_errors('Creation is not supported.') \
            .as_json_response(status=405)

    def update(self, request, *args, **kwargs):
        """推荐用于更新对象"""

        return self.result_builder \
            .set_errors('Updates are not supported.') \
            .as_json_response(status=405)

    def delete(self, request, *args, **kwargs):
        """推荐用于删除对象"""

        return self.result_builder \
            .set_errors('Deletion are not supported.') \
            .as_json_response(status=405)


class UnauthorizedErrorApiView(APIView):
    """未经授权错误API"""

    def get(self, request, *args, **kwargs):
        return self.result_builder \
            .set_errors('No access for unauthorized.') \
            .as_json_response(status=403)


class ServerErrorApiView(APIView):
    """内部服务错误API"""

    def get(self, request, *args, **kwargs):
        return self.result_builder \
            .set_errors('Internal server error.') \
            .as_json_response(status=500)


class UserEmailAPIView(APIView):
    """用户邮箱API"""

    def update(self, request, *args, **kwargs):
        if not ChangeEmailForm(request.POST).is_valid():
            return self.result_builder \
                .set_errors('Parameters format not correct error.') \
                .as_json_response(412)

        curr_email = request.POST['curr_email']
        new_email = request.POST['new_email']
        user = get_current_user(request)

        if user.email == curr_email:
            user.email = new_email
            user.save()

            return self.result_builder \
                .set_results('User-email changed successful.') \
                .as_json_response()
        else:
            return self.result_builder \
                .set_errors('The current user-email is incorrect.') \
                .as_json_response(412)


class UserPasswordAPIView(APIView):
    """用户密码API"""

    def update(self, request, *args, **kwargs):
        if not ChangePasswordBEForm(request.POST).is_valid():
            return self.result_builder \
                .set_errors('Parameters format not correct error.') \
                .as_json_response(412)

        curr_password = request.POST['curr_password']
        new_password = request.POST['new_password']
        new_password_again = request.POST['new_password_again']
        user = get_current_user(request)

        if new_password != new_password_again:
            return self.result_builder \
                .set_errors('Two new passwords do not match.') \
                .as_json_response(412)
        elif user.check_password(curr_password):
            user.password = new_password
            user.save()

            return self.result_builder \
                .set_results('User-password changed successful.') \
                .as_json_response()
        else:
            return self.result_builder \
                .set_errors('The current user-password is incorrect.') \
                .as_json_response(412)
