"""Home page route registrations."""

from flask import redirect, render_template, session, url_for

def register_home_routes(app, excel_service):
    """Register the dashboard/home route."""

    @app.route("/")
    def index():
        if "user" not in session:
            return redirect(url_for("login"))

        excel_service.ensure_excel_data_loaded()

        return render_template(
            "index.html",
            username=session.get("user"),
            vessel_devices=excel_service.vessel_devices,
            list_df=excel_service.list_df,
            summary_df=excel_service.summary_df,
            summary2_df=excel_service.summary2_df,
            summary3_df=excel_service.summary3_df,
            initiative_desc_map=excel_service.initiative_desc_map,
            listvessel_df=excel_service.listvessel_df,
            listdevice_df=excel_service.listdevice_df,
            kpis=excel_service.kpis,
            kpis_section=excel_service.kpis_section,
            fuel_data=excel_service.fuel_data,
            goal_data=excel_service.goal_data,
            fuel_latest=excel_service.fuel_latest,
            avg_latest=excel_service.avg_latest,
            goal_latest=excel_service.goal_latest,
            oil_data=excel_service.oil_data,
            cw_data=excel_service.cw_data,
            oil_latest=excel_service.oil_latest,
            ppm_latest=excel_service.ppm_latest,
            cond_latest=excel_service.cond_latest,
            vessels10=excel_service.vessels10,
            donutdev=excel_service.donutdev,
        )