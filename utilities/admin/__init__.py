# coding: utf-8
import re
import StringIO
import pickle
import json

from django.contrib import admin
from django.db import models
from django.utils.translation import ugettext_lazy as _
from django.http import HttpResponse
from django.utils.html import escape, escapejs, strip_spaces_between_tags
from django import forms
from django.http import HttpResponseRedirect
from django.utils.encoding import force_unicode, smart_str
from django.contrib.admin.views.main import ChangeList
from django.contrib import messages
from django.db import transaction, router
from django.http import Http404
from django.core.exceptions import PermissionDenied
from django.contrib.admin.util import get_deleted_objects
from django.contrib.admin.util import unquote
from django.contrib.admin.options import csrf_protect_m
from django.template.defaultfilters import slugify
from django.core.files.uploadedfile import UploadedFile
from django.utils import translation
try:
    from django.utils import simplejson
except ImportError:
    import simplejson

try:
    from django.utils.functional import update_wrapper
except ImportError:
    from functools import update_wrapper
from django.shortcuts import render_to_response
from django.core.files.base import ContentFile
from django.contrib.contenttypes.models import ContentType
from django.conf import settings
from django.utils import six
try:
    from django.utils.text import truncate_words
except ImportError:
    # django >=1.5
    from django.utils.text import Truncator
    from django.utils.functional import allow_lazy
    def truncate_words(s, num, end_text='...'):
        truncate = end_text and ' %s' % end_text or ''
        return Truncator(s).words(num, truncate=truncate)
    truncate_words = allow_lazy(truncate_words, six.text_type)
    
from utilities.deep_copy import deep_copy
from utilities.csv_generator import CsvGenerator
from utilities.models import HtmlMail, Recipient, Image, SiteEmail, GeneratedFile
from utilities.templatetags.generated_file import file_image, filename, sizify, is_error

from widgets import UpdateRelatedFieldWidgetWrapper
from django.core.urlresolvers import reverse

class RecipientInLine(admin.TabularInline):
    model = Recipient

class ImageInLine(admin.TabularInline):
    model = Image

class HtmlMailAdmin(admin.ModelAdmin):
    inlines = [RecipientInLine, ImageInLine]

    list_display = ('datetime', 'subject', 'recipients', 'status')

    def recipients(self, obj):
        recipitents = Recipient.objects.filter(htmlmail=obj)

        return truncate_words(u', '.join([force_unicode(recipient) for recipient in recipitents]), 10)
    recipients.short_description = _('Recipients')

    def status(self, obj):
        waiting_recipitents = Recipient.objects.filter(htmlmail=obj, sent=False)
        sent_recipitents = Recipient.objects.filter(htmlmail=obj, sent=True)


        if waiting_recipitents and sent_recipitents:
            background = '#FAE087'
            border = '#B0A16D'
            color = '#575755'
            status = _('Sending')
        elif sent_recipitents:
            background = '#C8DE96'
            border = '#94AC5E'
            color = '#585A56'
            status = _('Sent')
        else:
            background = '#BC3238'
            border = '#873034'
            color = '#FFFFFF'
            status = _('Waiting')

        return '<span style="display: block; text-align: center; width: 60px; padding: 1px 5px; background:%s;border-radius:3px;border:1px solid %s; color:%s;">%s</span>' % (background, border, color, force_unicode(status))
    status.short_description = _('State')
    status.allow_tags = True

admin.site.register(HtmlMail, HtmlMailAdmin)
admin.site.register(SiteEmail)





def get_related_delete(deleted_objects):
    if not isinstance(deleted_objects, list):
        return [deleted_objects, ]
    out = []
    for url in deleted_objects:
        out.extend(get_related_delete(url))
    return out


class RelatedToolsAdmin(admin.ModelAdmin):
    delete_confirmation_template = 'admin/delete_confirmation.html'

    @csrf_protect_m
    @transaction.atomic
    def delete_view(self, request, object_id, extra_context={}):
        if request.POST and "_popup" in request.POST:
            opts = self.model._meta

            obj = self.get_object(request, unquote(object_id))

            if not self.has_delete_permission(request, obj):
                raise PermissionDenied

            if obj is None:
                raise Http404(_('%(name)s object with primary key %(key)r does not exist.') % {'name': force_unicode(opts.verbose_name), 'key': escape(object_id)})

            using = router.db_for_write(self.model)

            (deleted_objects, perms_needed, protected) = get_deleted_objects(
            [obj], opts, request.user, self.admin_site, using)

            if perms_needed:
                raise PermissionDenied
            obj_display = force_unicode(obj)
            self.log_deletion(request, obj, obj_display)
            self.delete_model(request, obj)

            del_objects = []
            for url in get_related_delete(deleted_objects):
                url = unquote(url)
                import re
                m = re.match('.*href="/admin/([^/]*)/([^/]*)/([^/]*)/".*', unicode(url))
                # pro objekty, které nejsou zaregistrované v administraci url neexistuje. Co s tím?
                if m:
                    del_objects.append({'app': smart_str(m.group(1)), 'model': smart_str(m.group(2)), 'id':smart_str(m.group(3))})

            return HttpResponse(u'<script type="text/javascript">opener.dismissDeletePopup(window, %s);</script>' % \
                                del_objects)

        extra_context['is_popup'] = "_popup" in request.REQUEST
        return super(RelatedToolsAdmin, self).delete_view(request, object_id, extra_context=extra_context)




    def formfield_for_dbfield(self, db_field, **kwargs):
        if isinstance(db_field, (models.ForeignKey, models.ManyToManyField)):
            request = kwargs.pop("request", None)
            if db_field.__class__ in self.formfield_overrides:
                kwargs = dict(self.formfield_overrides[db_field.__class__], **kwargs)

            if isinstance(db_field, models.ForeignKey):
                formfield = self.formfield_for_foreignkey(db_field, request, **kwargs)
            elif isinstance(db_field, models.ManyToManyField):
                formfield = self.formfield_for_manytomany(db_field, request, **kwargs)


            if formfield and db_field.name not in self.raw_id_fields and (not hasattr(db_field.rel.to._meta, 'admin_foreign_key_tools') or db_field.rel.to._meta.admin_foreign_key_tools) and (not hasattr(db_field, 'admin_foreign_key_tools') or db_field.admin_foreign_key_tools):
                related_modeladmin = self.admin_site._registry.get(
                                                            db_field.rel.to)
                can_add_related = bool(related_modeladmin and
                            related_modeladmin.has_add_permission(request))

                formfield.widget = UpdateRelatedFieldWidgetWrapper(
                            formfield.widget, db_field.rel, self.admin_site,
                            can_add_related=can_add_related)

            return formfield
        return super(RelatedToolsAdmin, self).formfield_for_dbfield(db_field, **kwargs)


    def response_add(self, request, obj, post_url_continue='../%s/'):
        if "_popup" in request.POST:
            pk_value = obj._get_pk_val()
            return HttpResponse('<script type="text/javascript">opener.dismissAddAnotherPopup(window, "%s", "%s", %s);</script>' % \
                # escape() calls force_unicode.
                (escape(pk_value), escapejs(obj), json.dumps(self.popup_attrs(obj))))
        return super(RelatedToolsAdmin, self).response_add(request, obj, post_url_continue)

    def response_change(self, request, obj):
        if "_popup" in request.POST:
            pk_value = obj._get_pk_val()
            return HttpResponse('<script type="text/javascript">opener.dismissEditPopup(window, "%s", "%s", %s);</script>' % \
                # escape() calls force_unicode.
                (escape(pk_value), escapejs(obj), json.dumps(self.popup_attrs(obj))))
        return super(RelatedToolsAdmin, self).response_change(request, obj)



    def popup_attrs(self, obj):
        return {}


    def _media(self):
        media = super(RelatedToolsAdmin, self)._media()
        js = []
        js.append('%sutilities/js/jquery-1.6.4.min.js' % settings.STATIC_URL)
        js.append('%sutilities/admin/js/RelatedObjectLookups.js' % settings.STATIC_URL)
        media.add_js(js)
        return media
    media = property(_media)

class HiddenModelMixin(object):
    def get_model_perms(self, *args, **kwargs):
        perms = super(HiddenModelMixin, self).get_model_perms(*args, **kwargs)
        perms['list_hide'] = True
        return perms


class HiddenModelAdmin(HiddenModelMixin, RelatedToolsAdmin):
    pass

from django.contrib.admin.util import quote

class MarshallingChangeList(ChangeList):

    def url_for_result(self, result):
        return "../%s/%s/" % (getattr(result, self.model_admin.real_type_field).model, quote(getattr(result, self.pk_attname)))


class MarshallingAdmin(RelatedToolsAdmin):

    real_type_field = 'real_type'
    parent = None
    childs = []
    change_form_template = 'admin/marshalling_change_form.html'
    change_list_template = 'admin/marshalling_change_list.html'
    delete_confirmation_template = 'admin/marshalling_delete_confirmation.html'

    def get_changelist(self, request, **kwargs):
        return MarshallingChangeList

    def get_model_perms(self, *args, **kwargs):
        perms = super(MarshallingAdmin, self).get_model_perms(*args, **kwargs)
        if (self.parent != self.model):
            perms['list_hide'] = True
        perms['hide_add'] = True
        return perms

    def queryset(self, request, parent=False):
        if not parent:
            return super(MarshallingAdmin, self).queryset(request)
        qs = self.parent._default_manager.get_query_set()
        ordering = self.ordering or ()
        if ordering:
            qs = qs.order_by(*ordering)
        return qs

    def add_view(self, request, form_url='', extra_context={}):
        from django.contrib.contenttypes.models import ContentType
        if self.parent:
            extra_context['parent'] = self.parent.__name__.lower()

        return super(MarshallingAdmin, self).add_view(request, form_url, extra_context=extra_context)

    def change_view(self, request, object_id, extra_context={}):
        from django.contrib.contenttypes.models import ContentType
        if object_id:
            obj = self.get_object(request, object_id)
            if ContentType.objects.get_for_model(type(obj)) != getattr(obj, self.real_type_field):
                return HttpResponseRedirect('../../%s/%s' % (getattr(obj, self.real_type_field).model, object_id))

        if self.parent:
            extra_context['parent'] = self.parent.__name__.lower()

        return super(MarshallingAdmin, self).change_view(request, object_id, extra_context=extra_context)


    def changelist_view(self, request, extra_context={}):
        if self.childs:
            childs = []
            for obj in self.childs:
                childs.append({'name': obj.__name__.lower(), 'verbose_name': obj._meta.verbose_name})
            extra_context['childs'] = childs
        return super(MarshallingAdmin, self).changelist_view(request, extra_context=extra_context)

    @csrf_protect_m
    @transaction.atomic
    def delete_view(self, request, object_id, extra_context={}):
        if request.POST and not "_popup" in request.POST:
            opts = self.model._meta
            obj = self.get_object(request, unquote(object_id))

            if not self.has_delete_permission(request, obj):
                raise PermissionDenied

            if obj is None:
                raise Http404(_('%(name)s object with primary key %(key)r does not exist.') % {'name': force_unicode(opts.verbose_name), 'key': escape(object_id)})

            using = router.db_for_write(self.model)
            (deleted_objects, perms_needed, protected) = get_deleted_objects(
                [obj], opts, request.user, self.admin_site, using)


            if perms_needed:
                raise PermissionDenied
            obj_display = force_unicode(obj)
            self.log_deletion(request, obj, obj_display)
            self.delete_model(request, obj)

            self.message_user(request, _('The %(name)s "%(obj)s" was deleted successfully.') % {'name': force_unicode(opts.verbose_name), 'obj': force_unicode(obj_display)})

            if not self.has_change_permission(request, None):
                return HttpResponseRedirect("../../../../")
            return HttpResponseRedirect("../../../%s/" % self.parent.__name__.lower())

        if self.parent:
            extra_context['parent'] = self.parent.__name__.lower()
        return super(MarshallingAdmin, self).delete_view(request, object_id, extra_context=extra_context)

    def response_change(self, request, obj):
        if "_save" in request.POST:
            opts = obj._meta
            verbose_name = opts.verbose_name
            msg = _('The %(name)s "%(obj)s" was changed successfully.') % {'name': force_unicode(verbose_name), 'obj': force_unicode(obj)}
            self.message_user(request, msg)
            if self.has_change_permission(request, None):
                return HttpResponseRedirect('../../%s' % self.parent.__name__.lower())
            else:
                return HttpResponseRedirect('../../../')
        return super(MarshallingAdmin, self).response_change(request, obj)

    def response_add(self, request, obj, post_url_continue='../%s/'):
        if "_save" in request.POST:
            opts = obj._meta
            msg = _('The %(name)s "%(obj)s" was added successfully.') % {'name': force_unicode(opts.verbose_name), 'obj': force_unicode(obj)}
            self.message_user(request, msg)
            if self.has_change_permission(request, None):
                post_url = '../../%s' % self.parent.__name__.lower()
            else:
                post_url = '../../../'
            return HttpResponseRedirect(post_url)
        return super(MarshallingAdmin, self).response_add(request, obj, post_url_continue)


class MultipleFilesImportMixin(object):
    change_form_template = 'admin/multiple_file_upload_change_form.html'
    multiple_files_inline = None

    max_file_size = 5000000
    accept_file_types = []
    max_number_of_files = None

    def response_add(self, request, obj, post_url_continue='../%s/'):
        opts = obj._meta
        pk_value = obj._get_pk_val()

        msg = _('The %(name)s "%(obj)s" was added successfully.') % {'name': force_unicode(opts.verbose_name), 'obj': force_unicode(obj)}

        if "_continue_before_upload" in request.POST:
            self.message_user(request, msg + ' ' + force_unicode(_("You may edit it again below.")))
            post_url_continue += '?_upload=1'
            if "_popup" in request.POST:
                post_url_continue += "&_popup=1"
            return HttpResponseRedirect(post_url_continue % pk_value)
        return super(MultipleFilesImportMixin, self).response_add(request, obj, post_url_continue)

    def add_view(self, request, form_url='', extra_context={}):
        sup = super(MultipleFilesImportMixin, self)
        extra_context['multiplefilesimportmixin_super_template'] = sup.add_form_template or sup.change_form_template or 'admin/change_form.html'
        return sup.add_view(request, form_url, extra_context)

    def change_view(self, request, object_id, extra_context={}):
        sup = super(MultipleFilesImportMixin, self)
        extra_context['multiplefilesimportmixin_super_template'] = sup.change_form_template or 'admin/change_form.html'
        extra_context['max_file_size'] = self.max_file_size
        extra_context['accept_file_types'] = '|'.join(self.accept_file_types)
        extra_context['max_number_of_files'] = self.max_number_of_files
        extra_context['upload'] = request.GET.get('_upload', None)
        return sup.change_view(request, object_id, extra_context)

    def received_file(self, obj, file):
        return False

    def get_urls(self):
        from django.conf.urls.defaults import patterns, url
        info = self.model._meta.app_label, self.model._meta.module_name

        urlpatterns = patterns('',
            url(r'^(.+)/fileupload/$',
                self.fileupload_view,
                name='%s_%s_fileupload' % info),
        )

        urlpatterns += super(MultipleFilesImportMixin, self).get_urls()
        return urlpatterns


    def fileupload_view(self, request, object_id):
        obj = self.get_object(request, unquote(object_id))
        opts = self.model._meta

        if obj is None:
            raise Http404(_('%(name)s object with primary key %(key)r does not exist.') % {'name': force_unicode(opts.verbose_name), 'key': escape(object_id)})

        result = []

        if request.FILES.has_key('files[]') and request.FILES['files[]']:
            file = request.FILES['files[]']
            wrapped_file = UploadedFile(file)
            filename = wrapped_file.name
            file_size = wrapped_file.file.size

            if not self.received_file(obj, file):
                result.append({"error":'emptyResult', })
            else:
                result.append({"name":filename,
                                       "size":file_size,
                                      })
            response_data = simplejson.dumps(result)
        else:
            result.append({"error":6, })
        if "application/json" in request.META['HTTP_ACCEPT_ENCODING']:
            mimetype = 'application/json'
        else:
            mimetype = 'text/plain'

        return HttpResponse(response_data, mimetype=mimetype)

    def _media(self):
        media = super(MultipleFilesImportMixin, self)._media()
        js = []
        js.append('%sutilities/js/jquery-1.6.4.min.js' % settings.STATIC_URL)
        js.append('%sutilities/js/jquery.colorbox-min.js' % settings.STATIC_URL)
        media.add_js(js)

        css = {'screen': [], 'pring': []}
        css['screen'].append('%sutilities/css/colorbox.css' % settings.STATIC_URL)
        media.add_css(css)
        return media
    media = property(_media)


class DynamicListDisplayModelMixin(object):

    def __init__(self, model, admin_site):
        super(DynamicListDisplayModelMixin, self).__init__(model, admin_site)
        self.default_list_display = self.list_display

    def _change_list_display(self, list_display):
        list_display_copy = list(self.list_display)
        for field in self.list_display[1:]:
            list_display_copy.remove(field)

        self.list_display = list_display_copy

        for field in list_display:
            if (not field in self.list_display):
                self.list_display.append(field)

    def get_list_display(self, request):
        return self.default_list_display

    def changelist_view(self, request, extra_context=None):
        self._change_list_display(self.get_list_display(request))
        return super(DynamicListDisplayModelMixin, self).changelist_view(request, extra_context=extra_context)


class DynamicFieldsetsModelMixin(object):
    def __init__(self, model, admin_site):
        super(DynamicFieldsetsModelMixin, self).__init__(model, admin_site)
        self.default_fieldsets = self.fieldsets

    def change_view(self, request, object_id, extra_context=None):
        self.fieldsets = self.get_fieldsets(request)
        return super(DynamicFieldsetsModelMixin, self).change_view(request, object_id, extra_context=extra_context)

    def add_view(self, request, form_url='', extra_context=None):
        self.fieldsets = self.get_fieldsets(request)
        return super(DynamicFieldsetsModelMixin, self).add_view(request, form_url=form_url, extra_context=extra_context)

    def get_fieldsets(self, request, obj=None):
        if self.default_fieldsets:
            return self.default_fieldsets
        return super(DynamicFieldsetsModelMixin, self).get_fieldsets(request, obj=obj)


class CloneModelMixin(object):
    change_form_template = 'admin/clone_change_form.html'

    def pre_clone_save(self, obj):
        pass

    def response_change(self, request, obj):
        if ('_clone' in request.POST):
            opts = self.model._meta
            msg = _(u'The %(name)s "%(obj)s" was added successfully.') % {'name': force_unicode(opts.verbose_name), 'obj': force_unicode(obj)}
            copied_obj = deep_copy(obj, False)

            self.message_user(request, force_unicode(msg) + " " + force_unicode(_(u'Please update another values')))
            if "_popup" in request.REQUEST:
                return HttpResponseRedirect(request.path + "../%s?_popup=1" % copied_obj.pk)
            else:
                return HttpResponseRedirect(request.path + "../%s" % copied_obj.pk)

        return super(CloneModelMixin, self).response_change(request, obj)

    def add_view(self, request, form_url='', extra_context={}):
        sup = super(CloneModelMixin, self)
        extra_context['clonemodelmixin_super_template'] = sup.add_form_template or sup.change_form_template or 'admin/change_form.html'
        return sup.add_view(request, form_url, extra_context)

    def change_view(self, request, object_id, extra_context={}):
        sup = super(CloneModelMixin, self)
        extra_context['clonemodelmixin_super_template'] = sup.change_form_template or 'admin/change_form.html'
        return sup.change_view(request, object_id, extra_context)

    def _media(self):
        media = super(CloneModelMixin, self)._media()
        js = ['%sutilities/js/jquery-1.6.4.min.js' % settings.STATIC_URL]
        media.add_js(js)
        return media
    media = property(_media)

class AdminPagingMixin(object):
    change_form_template = 'admin/paging_change_form.html'
    page_ordering = 'pk'

    def add_view(self, request, form_url='', extra_context={}):
        sup = super(AdminPagingMixin, self)
        extra_context['pagingmixin_super_template'] = sup.add_form_template or sup.change_form_template or 'admin/change_form.html'
        return sup.add_view(request, form_url, extra_context)

    def change_view(self, request, object_id, extra_context={}):
        sup = super(AdminPagingMixin, self)

        model = self.model
        opts = model._meta

        obj = sup.get_object(request, object_id)
        if obj is None:
            raise Http404(_('%(name)s object with primary key %(key)r does not exist.') % {'name': force_unicode(opts.verbose_name), 'key': escape(object_id)})

        if hasattr(sup, 'parent'):
            qs = sup.queryset(request, True)
        else:
            qs = sup.queryset(request)

        qs = qs.order_by(self.page_ordering)
        next_qs = qs.filter(**{'%s__gt' % self.page_ordering:getattr(obj, self.page_ordering)}).order_by('%s' % self.page_ordering)
        prev_qs = qs.filter(**{'%s__lt' % self.page_ordering:getattr(obj, self.page_ordering)}).order_by('-%s' % self.page_ordering)

        if next_qs:
            extra_context['next_obj'] = {'app': next_qs[0]._meta.app_label, 'obj':next_qs[0]._meta.object_name.lower(), 'pk':next_qs[0]._get_pk_val(), 'verbose_name': next_qs[0]._meta.verbose_name}
        else:
            extra_context['next_obj'] = None
        if prev_qs:
            extra_context['prev_obj'] = {'app': prev_qs[0]._meta.app_label, 'obj':prev_qs[0]._meta.object_name.lower(), 'pk':prev_qs[0]._get_pk_val(), 'verbose_name': prev_qs[0]._meta.verbose_name}
        else:
            extra_context['prev_obj'] = None
        extra_context['pagingmixin_super_template'] = sup.change_form_template or 'admin/change_form.html'
        return sup.change_view(request, object_id, extra_context)

    def _media(self):
        media = super(AdminPagingMixin, self)._media()
        css = {'screen': ['%sutilities/admin/css/paging-admin.css' % settings.STATIC_URL]}
        media.add_css(css)
        return media
    media = property(_media)

class TreeChangeList(ChangeList):

    def tree_sort(self, parent):
        result = []
        ordering = self.model_admin.ordering
        filter_values = {self.model_admin.parent: parent}

        qs = self.result_list.filter(**filter_values)
        if (ordering):
            qs.order_by(ordering)
        for obj in qs:
            result = result + [obj.pk] + self.tree_sort(obj)
        return result

    def get_depth(self, obj):
        depth = 0
        parent = getattr(obj, self.model_admin.parent)
        obj.parent
        while(parent != None):
            parent = getattr(parent, self.model_admin.parent)
            depth += 1
        return depth

class TreeModelMixin(object):

    parent = None
    change_list_template = 'admin/change_tree.html'

    def queryset(self, request):
        qs = super(TreeModelMixin, self).queryset(request)

        for obj in qs:
            obj.depth = 0
        return qs

    def get_changelist(self, request, **kwargs):
        return TreeChangeList

    def changelist_view(self, request, extra_context={}):
        sup = super(TreeModelMixin, self)
        extra_context['treemodelmixin_super_template'] = sup.change_list_template or 'admin/change_list.html'
        return sup.changelist_view(request, extra_context)


class CSVImportForm(forms.Form):
    csv_file = forms.FileField(max_length=50)


class CSVExportMixin(object):
    # change_list_template = 'admin/csv_import_change_list.html'

    csv_delimiter = ';'
    csv_fields = ()
    csv_formatters = {}
    csv_quotechar = '"'
    csv_header = False
    csv_DB_values = False
    csv_bom = False
    csv_encoding = 'utf-8'

    actions = ['export_csv', ]

    def pre_import_save(self, obj):
        pass

    def import_csv(self, f):
        csv_generator = CsvGenerator(self, self.model, self.csv_fields, header=self.csv_header, delimiter=self.csv_delimiter, quotechar=self.csv_quotechar, DB_values=self.csv_DB_values, csv_formatters=self.csv_formatters, encoding=self.csv_encoding)
        obj = csv_generator.import_csv(f, self)
        return obj

    def export_csv(self, request, queryset):
        response = HttpResponse(mimetype='text/csv')
        response['Content-Disposition'] = 'attachment; filename=%s.csv' % slugify(queryset.model.__name__)
        if self.csv_bom:
            response.write("\xEF\xBB\xBF")
        csv_generator = CsvGenerator(self, self.model, self.get_csv_fields(request), header=self.csv_header, delimiter=self.csv_delimiter, quotechar=self.csv_quotechar, DB_values=self.csv_DB_values, csv_formatters=self.csv_formatters, encoding=self.csv_encoding)
        csv_generator.export_csv(response, queryset)
        return response

    export_csv.short_description = _(u"Export to CSV")

    def get_csv_fields(self, request):
        return self.csv_fields

    def changelist_view(self, request, extra_context={}):
        sup = super(CSVExportMixin, self)
        import_form = CSVImportForm()
        if ('_csv-import' in request.POST):
            import_form = CSVImportForm(request.POST, request.FILES)

            if(import_form.is_valid()):
                # try:
                self.import_csv(request.FILES['csv_file'])
                #    messages.info(request, _(u'CSV import byl úspěšně dokončen'))
                # except:
                #    messages.error(request, _(u'Špatný formát CSV souboru'))
            else:
                messages.error(request, _(u'File must be in CSV format.'))
            return HttpResponseRedirect('')
        extra_context['csvimportmixin_super_template'] = sup.change_list_template or 'admin/change_list.html'
        extra_context['import_form'] = import_form
        return sup.changelist_view(request, extra_context=extra_context)

class GeneratedFilesMixin(object):
    change_list_template = 'admin/generated_files_change_list.html'
    progress_image = '%sutilities/images/icons/progress.gif' % settings.STATIC_URL
    error_image = '%sutilities/images/icons/error.png' % settings.STATIC_URL
    file_images = {
                   'csv': '%sutilities/images/icons/CSV.png' % settings.STATIC_URL,
                   'zip': '%sutilities/images/icons/ZIP.png' % settings.STATIC_URL,
                   'pdf': '%sutilities/images/icons/PDF.png' % settings.STATIC_URL,
                }
    timeout = 120

    def get_urls(self):
        def wrap(view):
            def wrapper(*args, **kwargs):
                return self.admin_site.admin_view(view)(*args, **kwargs)
            return update_wrapper(wrapper, view)

        from django.conf.urls.defaults import patterns, url
        info = self.model._meta.app_label, self.model._meta.module_name
        urlpatterns = patterns('',
                               url(r'^generate-files/$', wrap(self.exported_files_view), name='%s_%s_exported_files' % info),
                               url(r'^generate-files/(.+)/$', wrap(self.exported_file_view), name='%s_%s_exported_file' % info),
                    ) + super(GeneratedFilesMixin, self).get_urls()
        return urlpatterns

    def changelist_view(self, request, extra_context={}):
        sup = super(GeneratedFilesMixin, self)
        extra_context['generated_files_super_template'] = sup.change_list_template or 'admin/change_list.html'
        return sup.changelist_view(request, extra_context=extra_context)

    def exported_files_view(self, request, extra_context={}):
        extra_context['exported_files'] = GeneratedFile.objects.filter(content_type=ContentType.objects.get_for_model(self.model)).order_by('-datetime')
        extra_context['STATIC_URL'] = settings.STATIC_URL
        extra_context['progress_image'] = self.progress_image
        extra_context['error_image'] = self.error_image
        extra_context['file_images'] = self.file_images
        extra_context['timeout'] = self.timeout

        return render_to_response('admin/generated_files.html', extra_context)

    def exported_file_view(self, request, object_id, extra_context={}):
        from django.utils import simplejson
        generated_file = GeneratedFile.objects.get(pk=object_id)
        if generated_file.file:
            json_data = {
                            'file_image': file_image(generated_file, self.file_images, self.progress_image, self.error_image, self.timeout),
                            'file_name':  filename(generated_file, self.timeout),
                            'file_url':   generated_file.file.url,
                            'file_size':  sizify(generated_file.file.size),
                            'generated':  True
                        }
        else:
            json_data = {
                            'generated': False,
                            'error': is_error(generated_file, self.timeout),
                            'file_image': self.error_image
                        }

        json_dump = simplejson.dumps(json_data)
        return HttpResponse(json_dump, mimetype='application/json')

    def _media(self):
        media = super(GeneratedFilesMixin, self)._media()
        js = (
              '%sutilities/js/jquery-1.6.4.min.js' % settings.STATIC_URL,
              '%sutilities/js/jquery.colorbox-min.js' % settings.STATIC_URL
              )
        media.add_js(js)

        css = {'screen': ['%sutilities/admin/css/colorbox.css' % settings.STATIC_URL]}
        media.add_css(css)
        return media
    media = property(_media)

class AsynchronousCSVExportMixin(GeneratedFilesMixin, CSVExportMixin):

    def export_csv(self, request, queryset):
        from utilities.tasks import generate_csv

        gf = GeneratedFile(content_type=ContentType.objects.get_for_model(self.model), count_objects=queryset.count())
        gf.save()
        messages.info(request, _(u'Objects is exporting to CSV'), extra_tags='generated-files-info')
        generate_csv.delay(gf.pk, self.model._meta.app_label, self.model._meta.object_name, queryset.values_list('pk', flat=True), self.csv_fields, translation.get_language())


class DashboardMixin(object):
    change_list_template = 'admin/dashboard_change_list.html'
    dashboard_table = []

    def changelist_view(self, request, extra_context={}):
        sup = super(DashboardMixin, self)
        extra_context['dashboardmixin_super_template'] = sup.change_list_template or 'admin/change_list.html'
        extra_context['show_dashboard'] = self.get_dashboard_table(request)
        return sup.changelist_view(request, extra_context=extra_context)

    def dashboard_view(self, request, extra_context={}):
        dashboard_table = []
        cl = self.get_changelist(request)(request, self.model, self.list_display, self.list_display_links, self.list_filter, self.date_hierarchy, self.search_fields, self.list_select_related, self.list_per_page, self.list_editable, self)
        qs = cl.get_query_set()


        media = {'js': [], 'css': {'print': [], 'screen': []}}

        row_num = 0
        for row in self.get_dashboard_table(request):
            dashboard_table_row = []

            col_num = 0
            for col in row:
                media = col.widget_instance.get_media(media)
                col.widget_instance.prefix = '%s-%s' % (row_num, col_num)
                dashboard_table_row.append({'colspan': col.get_colspan(), 'html':col.render(qs, self)})
                col_num += 1
            dashboard_table.append(dashboard_table_row)
            row_num += 1
        extra_context['media'] = media
        extra_context['dashboard_table'] = dashboard_table
        return render_to_response('admin/dashboard.html', extra_context)

    def get_dashboard_table(self, request):
        return self.dashboard_table


    def get_urls(self):
        def wrap(view):
            def wrapper(*args, **kwargs):
                return self.admin_site.admin_view(view)(*args, **kwargs)
            return update_wrapper(wrapper, view)

        from django.conf.urls.defaults import patterns, url
        info = self.model._meta.app_label, self.model._meta.module_name
        urlpatterns = patterns('', url(r'^dashboard/$', wrap(self.dashboard_view), name='%s_%s_dashboard' % info),) + super(DashboardMixin, self).get_urls()
        return urlpatterns

    def _media(self):
        media = super(DashboardMixin, self)._media()
        js = (
              '%sutilities/js/jquery-1.6.4.min.js' % settings.STATIC_URL,
              '%sutilities/js/jquery.colorbox-min.js' % settings.STATIC_URL
              )
        media.add_js(js)

        css = {'screen': ['%sutilities/admin/css/colorbox.css' % settings.STATIC_URL]}
        media.add_css(css)
        return media
    media = property(_media)

class HighlightedTabularInLine(admin.TabularInline):
    template = 'admin/edit_inline/highlighted_tabular.html'

    def _media(self):
        media = super(HighlightedTabularInLine, self)._media()
        js = []
        js.append('%sutilities/js/jquery-1.6.4.min.js' % settings.STATIC_URL)
        js.append('%sutilities/admin/js/highlighted-tabular.js' % settings.STATIC_URL)
        media.add_js(js)
        return media
    media = property(_media)


class DefaultFilterMixin(object):
    default_filters = ()

    def get_default_filters(self):
        return self.default_filters

    def changelist_view(self, request, *args, **kwargs):
        from django.http import HttpResponseRedirect
        default_filters = self.get_default_filters()

        if default_filters:
            try:
                test = request.META['HTTP_REFERER'].split(request.META['PATH_INFO'])
                if test and test[-1] and not test[-1].startswith('?'):
                    url = reverse('admin:%s_%s_changelist' % (self.opts.app_label, self.opts.module_name))
                    filters = []
                    for filter in default_filters:
                        key = filter.split('=')[0]
                        if not request.GET.has_key(key):
                            filters.append(filter)
                    if filters:
                        return HttpResponseRedirect("%s?%s" % (url, "&".join(filters)))
            except: pass
        return super(DefaultFilterMixin, self).changelist_view(request, *args, **kwargs)

try:
    from sorl.thumbnail.shortcuts import get_thumbnail
except ImportError:
    pass
else:
    from .sorl_thumbnail import AdminImageMixin
