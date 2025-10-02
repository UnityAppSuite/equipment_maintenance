import frappe
from frappe.model.document import Document
from frappe import _

class MaintenanceWorkOrder(Document):
    def on_submit(self):
        # The trigger condition now checks if the single 'link_gtub' field has a value.
        if self.link_gtub:
            self.create_material_request()

    def create_material_request(self):
        try:
            # Create the Material Request document in memory.
            material_request = frappe.get_doc({
                "doctype": "Material Request",
                "material_request_type": "Purchase",
                "company": "Demo",
                "custom_maintenance_work_order": self.name 
            })
            material_request.append("items", {
                "item_code": self.link_gtub,
                "qty": 1, 
                "schedule_date": self.scheduled_date or frappe.utils.today()
            })
            
            material_request.insert(ignore_permissions=True)
            material_request.submit()
            
            frappe.msgprint(
                _("Material Request <a href='/app/material-request/{0}'>{0}</a> created.").format(material_request.name),
                indicator="green"
            )

        except Exception as e:
            frappe.log_error(frappe.get_traceback(), "Material Request Creation Failed")
            frappe.throw(_("Failed to create Material Request: {0}").format(e))
