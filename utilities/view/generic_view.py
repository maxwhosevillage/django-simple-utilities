# coding: utf-8
from django.views.generic import ListView, DetailView, TemplateView
from django.shortcuts import HttpResponseRedirect
from django.contrib import messages
from django.utils.encoding import force_unicode

class FormsMixin(object):
    success_url = {}
    forms_class = {}
    initials = {}
    messages_valid = {}
    messages_invalid = {}
    
    def get_valid_message(self, form, form_key):
        if self.messages_valid.get(form_key):
            return self.messages_valid.get(form_key)
        return self.messages_valid.get('default')
    
    def get_invalid_message(self, form, form_key):
        if self.messages_invalid.get(form_key):
            return self.messages_invalid.get(form_key)
        return self.messages_invalid.get('default')
    
    def form_invalid(self, form, form_key, message_text= None):
        message_text = message_text or self.get_invalid_message(form, form_key)
        if message_text:
            messages.error(
                self.request,
                force_unicode(message_text),
                extra_tags=form_key
            )
        return self.get(self.request)
    
    def form_valid(self, form, form_key, message_text = None):
        message_text = message_text or self.get_valid_message(form, form_key)
        if message_text:
            messages.success(
                self.request,
                force_unicode(message_text),
                extra_tags=form_key
            )
        return HttpResponseRedirect(self.get_success_url(form_key))
    
    def get_success_url(self, form_key):
        path = self.request.path
        split_path = path.split('/')
        split_path = filter(None, split_path)
        
        if split_path:
            for key, form in self.forms_class.items():
                if split_path[-1] == self.success_url.get(key):
                    del split_path[-1]
                    break

        if self.success_url.get(form_key):
            split_path.append(self.success_url.get(form_key))

        return '/%s/' % '/'.join(split_path)
    
    def get_context_data(self, **kwargs):
        context = super(FormsMixin, self).get_context_data(**kwargs)
        context['forms'] = self.get_forms()
        return context
    
    def post(self, request, *args, **kwargs):
        forms = self.get_forms()
        for key, val in forms.items():
            if (key in self.request.POST):
                if (val.is_valid()):
                    return self.form_valid(val, key)
                else:
                    return self.form_invalid(val, key)

    def get_form_messages(self, tag):
        form_messages =[]
        for message in messages.get_messages(self.request):
            if (message.extra_tags == tag):
                form_messages.append(message)
        return form_messages
        
    def get_form(self, form_class, form_key):
        form = form_class(**self.get_form_kwargs(form_key))
        form.messages = self.get_form_messages(form_key)
        return form
    
    def get_form_kwargs(self, form_key):
        kwargs = {'initial': self.get_initial(form_key)}
        if self.request.method in ('POST', 'PUT') and form_key in self.request.POST:
            kwargs.update({
                'data': self.request.POST,
                'files': self.request.FILES,
            })
        return kwargs
    
    def get_initial(self, form_key):
        return self.initials.get(form_key)
        
    def get_forms(self):
        forms = {}
        for key, val in self.forms_class.items():
            forms[key] = self.get_form(val, key)
        return forms


class DetailFormsView(FormsMixin, DetailView):
    pass
    
    
    
class ListFormsView(FormsMixin, ListView):
    pass
    
    
class FormsView(FormsMixin, TemplateView):
    pass
    