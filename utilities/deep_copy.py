# coding: utf-8
import re

from copy import copy as copy_object

def change_id(obj, id):
    def change_related(obj, old):
        for link in [rel.get_accessor_name() for rel in old._meta.get_all_related_objects()]:
            objects = getattr(old, link).all()
            for rel_obj in objects:
                for field in rel_obj._meta.fields:
                    if field.get_internal_type() == "ForeignKey" and isinstance(obj, field.rel.to):
                        setattr(rel_obj, field.name, obj)
                rel_obj.save()

    old = obj.__class__.objects.get(id = obj.id)
    obj.id = id
    super(obj.__class__, obj).save()
    change_related(obj, old)
    old.delete()  
    


def get_args(obj, fields):
    args = {}
    for field in fields:
        args[field] =  getattr(obj, field)
    return args
    
def rename_unique_together(obj):
    for unique_together in obj._meta.unique_together:  
        if obj.__class__._default_manager.filter(**get_args(obj, unique_together)):
            for field in unique_together:
                if obj._meta.get_field(field).get_internal_type() ==  "CharField":
                    val = getattr(obj, field)
                    if val != None:
                        m = re.match(r'^.* \((\d+)\)$', val)
                        i = 1
                        if m:
                            i =  int(m.group(1)) + 1
                        origin_val = re.sub(r' \(\d+\)$', '', val)
                        val = origin_val + ' (%s)' % i
                        setattr(obj, field, val)
                        
                        while obj.__class__._default_manager.filter(**get_args(obj, unique_together)):
                            val = origin_val + ' (%s)' % i
                            i += 1
                            setattr(obj, field, val)
                    break

def rename_unique(obj):
    for field in obj._meta.fields:
        if (field.get_internal_type() ==  "CharField" and field.unique):
            val = getattr(obj, field.name)
            if val != None:
                m = re.match(r'^.* \((\d+)\)$', val)
                i = 1
                if m:
                    i =  int(m.group(1)) + 1
                origin_val = re.sub(r' \(\d+\)$', '', val)
                val = origin_val + ' (%s)' % i
                while (obj.__class__._default_manager.filter(**{field.name: val})):
                    val = origin_val + ' (%s)' % i
                    i += 1

            setattr(obj, field.name, val)
    

def deep_copy(obj, copy_related = True): 
    
    copied_obj = copy_object(obj) 
    copied_obj.id = None 
    
    if hasattr(copied_obj,'clone'):
        copied_obj.clone() 
    rename_unique(copied_obj)
    rename_unique_together(copied_obj)
    copied_obj.save() 
       
    for original, copy in zip(obj._meta.many_to_many, copied_obj._meta.many_to_many): 
        # get the managers of the fields 
        source = getattr(obj, original.attname) 
        destination = getattr(copied_obj, copy.attname) 
        # copy m2m field contents 
        for element in source.all(): 
            destination.add(element) 
          
    # save for a second time (to apply the copied many to many fields) 
    
    if hasattr(copied_obj,'clone'):
        copied_obj.clone() 
    copied_obj.save() 
        
    if (copy_related):   
        # clone related objects
        links = [rel.get_accessor_name() for rel in obj._meta.get_all_related_objects()]

        for link in links:
            for original in getattr(obj, link).all():
                copied_related = deep_copy(original)
                for field in copied_related._meta.fields:
                    #set foreign key to copied_obj
                    if (getattr(copied_related, field.name) == obj):
                        setattr(copied_related, field.name, copied_obj)
                if hasattr(copied_related,'clone'):
                    copied_related.clone() 
                rename_unique(copied_related)
                copied_related.save()
        
    return copied_obj 