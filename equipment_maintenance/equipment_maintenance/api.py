
import frappe

@frappe.whitelist()
def get_dashboard_data():
    active_equipment = frappe.db.count("Equipment Registry", {"status": "Active"})
    maintenance_equipment = frappe.db.count("Equipment Registry", {"status": "Under Maintenance"})
    wos_in_progress = frappe.db.count("Maintenance Work Order", {"status": "In Progress"})

    return {
        "active_equipment": active_equipment,
        "under_maintenance": maintenance_equipment,
        "work_orders_in_progress": wos_in_progress,
    }


@frappe.whitelist()
def get_equipment_history(equipment):
    if not equipment:
        return []

    history = frappe.get_all(
        "Maintenance Work Order",
        filters={"equipment": equipment},
        fields=["name", "status", "completion_date", "total_cost"],
        order_by="completion_date desc",
    )
    return history


@frappe.whitelist()
def update_work_order_status(work_order_id, status):
    """Updates the status of a work order, typically from a mobile app."""
    try:
        wo = frappe.get_doc("Maintenance Work Order", work_order_id)
        wo.status = status
        wo.save(ignore_permissions=True) 
        frappe.db.commit()
        return {"status": "success", "message": f"Work Order {work_order_id} status updated to {status}"}
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "update_work_order_status Error")
        return {"status": "error", "message": str(e)}