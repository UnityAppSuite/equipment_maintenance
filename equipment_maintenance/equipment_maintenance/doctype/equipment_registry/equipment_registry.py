# Copyright (c) 2025, sathwik and contributors
# For license information, please see license.txt
from __future__ import annotations
import frappe
from frappe.model.document import Document
from frappe.utils import add_days, add_months, getdate, today


def _add_interval(start, frequency: str, cycle_no: int):
    if frequency == "Daily":
        return add_days(start, cycle_no * 1)
    if frequency == "Weekly":
        return add_days(start, cycle_no * 7)
    if frequency == "Monthly":
        return add_months(start, cycle_no * 1)
    if frequency == "Quarterly":
        return add_months(start, cycle_no * 3)
    if frequency == "Yearly":
        return add_months(start, cycle_no * 12)
    return None


def _get_checklist_rows_with_frequency(equipment_type: str) -> list[dict]:
    if not equipment_type:
        return []
    return frappe.get_all(
        "Standard Maintenance Checklist Item",
        filters={
            # make sure this matches the *child table fieldname* in your parent doctype
            "parentfield": "standard_maintenance_checklist_table_with_checkpoints",
        },
        fields=["checkpoint", "description", "frequency"],
        order_by="idx asc",
    )


def _mwo_exists(equipment: str, scheduled_date, task_description: str) -> bool:
    return bool(
        frappe.db.exists(
            "Maintenance Work Order",
            {
                "equipment": equipment,
                "work_order_type": "Preventive",
                "scheduled_date": getdate(scheduled_date),
                "description": task_description,
            },
        )
    )


@frappe.whitelist()
def schedule_preventive_work_orders(equipment_name: str):
    eq = frappe.get_doc("Equipment Registry", equipment_name)

    # skip decommissioned
    if (eq.status or "").strip().lower() == "decommissioned":
        frappe.msgprint(f"Skipping: {eq.name} is Decommissioned.")
        frappe.logger().info(f"[AutoSchedule] skip decommissioned {equipment_name}")
        return

    start_date = getdate(eq.installation_date) if eq.installation_date else getdate(today())
    checklist_items = _get_checklist_rows_with_frequency(eq.equipment_type)

    if not checklist_items:
        frappe.msgprint(f"No checklist items with frequency for Equipment Type {eq.equipment_type}")
        frappe.logger().info(f"[AutoSchedule] no checklist rows for {equipment_name}")
        return

    first_due_overall = None
    total_created = 0
    cycles = 4  

    for item in checklist_items:
        frequency = (item.get("frequency") or "").strip()
        if not frequency:
            frappe.logger().info(f"[AutoSchedule] skip (no frequency) item={item}")
            continue

        task_description = item.get("checkpoint") or item.get("description") or "Checklist Task"

        for k in range(1, cycles + 1):
            due_date = _add_interval(start_date, frequency, k)
            if not due_date:
                continue

            if _mwo_exists(eq.name, due_date, task_description):
                frappe.logger().info(f"[AutoSchedule] exists {task_description} {due_date}")
                continue

            mwo = frappe.new_doc("Maintenance Work Order")
            mwo.update({
                "work_order_type": "Preventive",
                "equipment": eq.name,
                "scheduled_date": due_date,
                "status": "Scheduled",
                "priority": "Medium",
                "assigned_technician": eq.assigned_technician,
                "description": f"{task_description} ({frequency})",
            })
            mwo.append("maintenance_tasks", {
                "task_description": task_description,
                "is_completed": 0
            })
            mwo.insert(ignore_permissions=True)
            frappe.logger().info(f"[AutoSchedule] created MWO {mwo.name} for {task_description}")
            total_created += 1

            if not first_due_overall or due_date < first_due_overall:
                first_due_overall = due_date

    if first_due_overall:
        eq.db_set("next_maintenance_due", getdate(first_due_overall))

    frappe.msgprint(f"Auto-scheduling: created {total_created} preventive MWO(s) for {eq.name}.")
    frappe.logger().info(f"[AutoSchedule] finish {equipment_name} created={total_created}")


class EquipmentRegistry(Document):
    """Controller for Equipment Registry"""

    def after_insert(self):
        """
        Triggered automatically after a new Equipment Registry record is created.
        Schedules preventive MWOs and notifies the assigned tech.
        """
        try:
            frappe.logger().info(f"[AutoSchedule] after_insert for {self.name}")
            schedule_preventive_work_orders(self.name)
        except Exception:
            frappe.log_error("Auto-scheduling MWOs failed", frappe.get_traceback())

        # keep email independent; failure here shouldn't block insert
        try:
            self.notify_assigned_technician()
        except Exception:
            frappe.log_error(frappe.get_traceback(), "EquipmentRegistry.after_insert: notify failed")

    @frappe.whitelist()
    def notify_assigned_technician(self):
        """Send email to the assigned technician of this equipment registry."""
        if not self.assigned_technician:
            return {"success": False, "error": "No assigned technician set."}

        emp = frappe.db.get_value(
            "Employee",
            self.assigned_technician,
            ["company_email", "personal_email", "user_id"],
            as_dict=True
        ) or {}

        recipient = emp.get("company_email") or emp.get("personal_email")
        if not recipient and emp.get("user_id"):
            recipient = frappe.get_cached_value("User", emp.get("user_id"), "email")

        if not recipient:
            try:
                if self.meta.get_field("email_sent"):
                    self.db_set("email_sent", 0)
            except Exception:
                pass
            return {"success": False, "error": "Assigned employee has no email configured."}

        subject = f"Equipment Assigned: {self.equipment_name or self.name}"
        message = frappe.render_template("""
            <p>Hi {{tech_name}},</p>
            <p>You have been assigned responsibility for Equipment <b>{{eq_name}}</b>.</p>
            <p><b>Details:</b><br>
            - Type: {{eq_type}}<br>
            - Description: {{description}}<br>
            - Registry ID: {{registry}}</p>
            <p>Regards,<br>{{company}}</p>
        """, {
            "tech_name": self.assigned_technician,
            "eq_name": self.equipment_name or self.name,
            "eq_type": self.equipment_type or "N/A",
            "description": self.get("description") or "N/A",
            "registry": self.name,
            "company": frappe.db.get_single_value("Global Defaults", "default_company") or ""
        })

        try:
            frappe.sendmail(
                recipients=[recipient],
                subject=subject,
                message=message,
                reference_doctype=self.doctype,
                reference_name=self.name,
                retry=False
            )
            try:
                if self.meta.get_field("email_sent"):
                    self.db_set("email_sent", 1)
            except Exception:
                frappe.log_error(frappe.get_traceback(), "EquipmentRegistry.notify_assigned_technician: db_set email_sent failed")
            return {"success": True, "email_sent": True}
        except Exception as e:
            frappe.log_error(frappe.get_traceback(), "Send Email (Equipment Registry)")
            try:
                if self.meta.get_field("email_sent"):
                    self.db_set("email_sent", 0)
            except Exception:
                pass
            return {"success": False, "error": str(e)}
