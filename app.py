from flask import Flask, render_template, jsonify, request, Response

import csv
import io
import json
from urllib.request import urlopen
from urllib.error import URLError, HTTPError

from spc.xbar_r import calculate_xbar_r
from spc.imr import calculate_imr
from spc.xbar_s import calculate_xbar_s
from spc.p_chart import calculate_p_chart
from spc.np_chart import calculate_np_chart
from spc.c_chart import calculate_c_chart
from spc.u_chart import calculate_u_chart

from database.db import (
    create_tables,
    save_measurement,
    save_alarm,
    get_recent_alarms,
    get_recent_measurements
)


app = Flask(__name__)

create_tables()


spc_config = {
    "process_name": "Bottle Filling",
    "chart_type": "xbar_r",
    "subgroup_size": 5,
    "sample_size": 100,
    "alarm_sound": "on"
}


current_subgroup = []


xbar_reference_data = [
    [500.1, 500.3, 499.9, 500.2, 500.0],
    [500.4, 500.1, 500.2, 500.3, 500.0],
    [499.8, 500.0, 500.1, 499.9, 500.2],
    [500.2, 500.3, 500.1, 500.4, 500.0],
    [499.9, 500.1, 500.0, 500.2, 499.8]
]


imr_values = [
    500.1,
    500.2,
    499.9,
    500.3,
    500.0
]


p_defectives = [
    4,
    5,
    3,
    6,
    4
]


p_sample_sizes = [
    100,
    100,
    100,
    100,
    100
]


np_defectives = [
    4,
    5,
    3,
    6,
    4
]


c_defect_counts = [
    4,
    5,
    3,
    6,
    4
]


u_defect_counts = [
    4,
    5,
    3,
    6,
    4
]


u_sample_sizes = [
    100,
    100,
    100,
    100,
    100
]



SIMULATOR_DATA_URL = "https://spc-simulator.onrender.com/api/data"
simulator_last_id = 0

def get_next_simulator_data(chart_type):
    global simulator_last_id
    expected = "variable" if chart_type in ("xbar_r", "xbar_s", "imr") else "attribute"
    try:
        with urlopen(f"{SIMULATOR_DATA_URL}?after_id={simulator_last_id}", timeout=2) as r:
            payload = json.loads(r.read().decode("utf-8"))
    except (URLError, HTTPError, TimeoutError, ValueError, json.JSONDecodeError):
        return None
    for item in sorted(payload.get("data", []), key=lambda x: int(x.get("id", 0))):
        item_id = int(item.get("id", 0))
        simulator_last_id = max(simulator_last_id, item_id)
        if item.get("data_type") == expected:
            return item
    return None

def waiting_for_simulator(chart_type):
    return jsonify({
        "chart_type": chart_type,
        "waiting": True,
        "simulator_waiting": True,
        "alarm": False,
        "alarm_reason": None,
        "message": "Waiting for new data from SPC Simulator."
    })

@app.route("/")
def home():

    return render_template(
        "index.html"
    )


@app.route(
    "/api/config",
    methods=["GET", "POST"]
)
def configuration():

    global spc_config
    global current_subgroup

    if request.method == "POST":

        data = request.get_json()

        chart_type = data.get(
            "chart_type",
            "xbar_r"
        )

        subgroup_size = int(
            data.get(
                "subgroup_size",
                5
            )
        )

        sample_size = int(
            data.get(
                "sample_size",
                100
            )
        )

        if subgroup_size < 2:
            subgroup_size = 2

        if subgroup_size > 10:
            subgroup_size = 10

        if sample_size < 1:
            sample_size = 1

        spc_config = {
            "process_name":
                data.get(
                    "process_name",
                    "Bottle Filling"
                ),

            "chart_type":
                chart_type,

            "subgroup_size":
                subgroup_size,

            "sample_size":
                sample_size,

            "alarm_sound":
                data.get(
                    "alarm_sound",
                    "on"
                )
        }

        current_subgroup = []

        return jsonify({
            "success": True,
            "config": spc_config
        })

    return jsonify(
        spc_config
    )


@app.route("/api/measurement")
def measurement():

    global current_subgroup
    global imr_values
    global p_defectives
    global p_sample_sizes
    global np_defectives
    global c_defect_counts
    global u_defect_counts
    global u_sample_sizes

    chart_type = (
        spc_config["chart_type"]
    )

    response = {
        "chart_type": chart_type,
        "alarm": False,
        "alarm_reason": None
    }

    observation = get_next_simulator_data(chart_type)
    if observation is None:
        return waiting_for_simulator(chart_type)


    if chart_type == "xbar_r":

        value = float(observation["value"])

        save_measurement(value)

        current_subgroup.append(value)

        subgroup_size = (
            spc_config["subgroup_size"]
        )

        response.update({
            "value": value,
            "waiting": True,
            "subgroup_progress":
                len(current_subgroup),
            "subgroup_size":
                subgroup_size
        })

        if (
            len(current_subgroup)
            >= subgroup_size
        ):

            new_subgroup = (
                current_subgroup.copy()
            )

            current_subgroup = []

            reference_data = [
                row[:subgroup_size]
                for row
                in xbar_reference_data
                if len(row) >= subgroup_size
            ]


            previous_result = (
                calculate_xbar_r(
                    reference_data
                )
            )

            subgroup_mean = (
                sum(new_subgroup)
                / len(new_subgroup)
            )

            if (
                subgroup_mean
                > previous_result[
                    "xbar_ucl"
                ]
            ):

                response["alarm"] = True

                response["alarm_reason"] = (
                    "Subgroup mean exceeded UCL"
                )

                save_alarm(
                    subgroup_mean,
                    response[
                        "alarm_reason"
                    ]
                )

            elif (
                subgroup_mean
                < previous_result[
                    "xbar_lcl"
                ]
            ):

                response["alarm"] = True

                response["alarm_reason"] = (
                    "Subgroup mean fell below LCL"
                )

                save_alarm(
                    subgroup_mean,
                    response[
                        "alarm_reason"
                    ]
                )

            reference_data.append(
                new_subgroup
            )

            result = calculate_xbar_r(
                reference_data
            )

            response.update({
                "waiting": False,
                "subgroup_means":
                    result["subgroup_means"],
                "subgroup_ranges":
                    result["subgroup_ranges"],
                "center":
                    result["xbar"],
                "ucl":
                    result["xbar_ucl"],
                "lcl":
                    result["xbar_lcl"],
                "secondary_center":
                    result["rbar"],
                "secondary_ucl":
                    result["r_ucl"],
                "secondary_lcl":
                    result["r_lcl"]
            })


    elif chart_type == "xbar_s":

        value = float(observation["value"])

        save_measurement(value)

        current_subgroup.append(value)

        subgroup_size = (
            spc_config["subgroup_size"]
        )

        response.update({
            "value": value,
            "waiting": True,
            "subgroup_progress":
                len(current_subgroup),
            "subgroup_size":
                subgroup_size
        })

        if (
            len(current_subgroup)
            >= subgroup_size
        ):

            new_subgroup = (
                current_subgroup.copy()
            )

            current_subgroup = []

            reference_data = [
                row[:subgroup_size]
                for row
                in xbar_reference_data
                if len(row) >= subgroup_size
            ]


            previous_result = (
                calculate_xbar_s(
                    reference_data
                )
            )

            subgroup_mean = (
                sum(new_subgroup)
                / len(new_subgroup)
            )

            if (
                subgroup_mean
                > previous_result[
                    "xbar_ucl"
                ]
            ):

                response["alarm"] = True

                response["alarm_reason"] = (
                    "Subgroup mean exceeded UCL"
                )

                save_alarm(
                    subgroup_mean,
                    response["alarm_reason"]
                )

            elif (
                subgroup_mean
                < previous_result[
                    "xbar_lcl"
                ]
            ):

                response["alarm"] = True

                response["alarm_reason"] = (
                    "Subgroup mean fell below LCL"
                )

                save_alarm(
                    subgroup_mean,
                    response["alarm_reason"]
                )

            reference_data.append(
                new_subgroup
            )

            result = calculate_xbar_s(
                reference_data
            )

            response.update({
                "waiting": False,
                "subgroup_means":
                    result["subgroup_means"],
                "subgroup_std":
                    result["subgroup_std"],
                "center":
                    result["xbar"],
                "ucl":
                    result["xbar_ucl"],
                "lcl":
                    result["xbar_lcl"],
                "secondary_center":
                    result["sbar"],
                "secondary_ucl":
                    result["s_ucl"],
                "secondary_lcl":
                    result["s_lcl"]
            })


    elif chart_type == "imr":

        value = float(observation["value"])

        save_measurement(value)

        previous_result = (
            calculate_imr(
                imr_values
            )
        )

        if (
            value
            > previous_result["i_ucl"]
        ):

            response["alarm"] = True

            response["alarm_reason"] = (
                "Individual value exceeded UCL"
            )

            save_alarm(
                value,
                response["alarm_reason"]
            )

        elif (
            value
            < previous_result["i_lcl"]
        ):

            response["alarm"] = True

            response["alarm_reason"] = (
                "Individual value fell below LCL"
            )

            save_alarm(
                value,
                response["alarm_reason"]
            )

        imr_values.append(value)

        if len(imr_values) > 40:
            imr_values.pop(0)

        result = calculate_imr(
            imr_values
        )

        response.update({
            "value": value,
            "values":
                result["values"],
            "moving_ranges":
                result["moving_ranges"],
            "center":
                result["mean"],
            "ucl":
                result["i_ucl"],
            "lcl":
                result["i_lcl"],
            "secondary_center":
                result["mr_bar"],
            "secondary_ucl":
                result["mr_ucl"],
            "secondary_lcl":
                result["mr_lcl"]
        })


    elif chart_type == "p_chart":

        sample_size = int(observation.get("sample_size", spc_config["sample_size"]))
        defective_count = int(observation["defect_count"])

        proportion = (
            defective_count
            / sample_size
        )

        save_measurement(
            proportion
        )

        previous_result = (
            calculate_p_chart(
                p_defectives,
                p_sample_sizes
            )
        )

        previous_ucl = (
            previous_result["ucl"][-1]
        )

        previous_lcl = (
            previous_result["lcl"][-1]
        )

        if proportion > previous_ucl:

            response["alarm"] = True

            response["alarm_reason"] = (
                "Defective proportion exceeded UCL"
            )

            save_alarm(
                proportion,
                response["alarm_reason"]
            )

        elif proportion < previous_lcl:

            response["alarm"] = True

            response["alarm_reason"] = (
                "Defective proportion fell below LCL"
            )

            save_alarm(
                proportion,
                response["alarm_reason"]
            )

        p_defectives.append(
            defective_count
        )

        p_sample_sizes.append(
            sample_size
        )

        if len(p_defectives) > 40:
            p_defectives.pop(0)
            p_sample_sizes.pop(0)

        result = calculate_p_chart(
            p_defectives,
            p_sample_sizes
        )

        response.update({
            "value": proportion,
            "defective_count":
                defective_count,
            "sample_size":
                sample_size,
            "proportions":
                result["proportions"],
            "center":
                result["pbar"],
            "ucl_values":
                result["ucl"],
            "lcl_values":
                result["lcl"]
        })


    elif chart_type == "np_chart":

        sample_size = int(observation.get("sample_size", spc_config["sample_size"]))
        defective_count = int(observation["defect_count"])

        save_measurement(
            defective_count
        )

        previous_result = (
            calculate_np_chart(
                np_defectives,
                sample_size
            )
        )

        if (
            defective_count
            > previous_result["ucl"]
        ):

            response["alarm"] = True

            response["alarm_reason"] = (
                "Defective count exceeded UCL"
            )

            save_alarm(
                defective_count,
                response["alarm_reason"]
            )

        elif (
            defective_count
            < previous_result["lcl"]
        ):

            response["alarm"] = True

            response["alarm_reason"] = (
                "Defective count fell below LCL"
            )

            save_alarm(
                defective_count,
                response["alarm_reason"]
            )

        np_defectives.append(
            defective_count
        )

        if len(np_defectives) > 40:
            np_defectives.pop(0)

        result = calculate_np_chart(
            np_defectives,
            sample_size
        )

        response.update({
            "value":
                defective_count,
            "defective_count":
                defective_count,
            "sample_size":
                sample_size,
            "defectives":
                result["defectives"],
            "center":
                result["npbar"],
            "ucl":
                result["ucl"],
            "lcl":
                result["lcl"]
        })


    elif chart_type == "c_chart":

        defect_count = int(observation["defect_count"])

        save_measurement(
            defect_count
        )

        previous_result = (
            calculate_c_chart(
                c_defect_counts
            )
        )

        if (
            defect_count
            > previous_result["ucl"]
        ):

            response["alarm"] = True

            response["alarm_reason"] = (
                "Defect count exceeded UCL"
            )

            save_alarm(
                defect_count,
                response["alarm_reason"]
            )

        elif (
            defect_count
            < previous_result["lcl"]
        ):

            response["alarm"] = True

            response["alarm_reason"] = (
                "Defect count fell below LCL"
            )

            save_alarm(
                defect_count,
                response["alarm_reason"]
            )

        c_defect_counts.append(
            defect_count
        )

        if len(c_defect_counts) > 40:
            c_defect_counts.pop(0)

        result = calculate_c_chart(
            c_defect_counts
        )

        response.update({
            "value":
                defect_count,
            "defect_count":
                defect_count,
            "defect_counts":
                result["defect_counts"],
            "center":
                result["cbar"],
            "ucl":
                result["ucl"],
            "lcl":
                result["lcl"]
        })


    elif chart_type == "u_chart":

        sample_size = int(observation.get("sample_size", spc_config["sample_size"]))
        defect_count = int(observation["defect_count"])

        defects_per_unit = (
            defect_count
            / sample_size
        )

        save_measurement(
            defects_per_unit
        )

        previous_result = (
            calculate_u_chart(
                u_defect_counts,
                u_sample_sizes
            )
        )

        previous_ucl = (
            previous_result["ucl"][-1]
        )

        previous_lcl = (
            previous_result["lcl"][-1]
        )

        if (
            defects_per_unit
            > previous_ucl
        ):

            response["alarm"] = True

            response["alarm_reason"] = (
                "Defects per unit exceeded UCL"
            )

            save_alarm(
                defects_per_unit,
                response["alarm_reason"]
            )

        elif (
            defects_per_unit
            < previous_lcl
        ):

            response["alarm"] = True

            response["alarm_reason"] = (
                "Defects per unit fell below LCL"
            )

            save_alarm(
                defects_per_unit,
                response["alarm_reason"]
            )

        u_defect_counts.append(
            defect_count
        )

        u_sample_sizes.append(
            sample_size
        )

        if len(u_defect_counts) > 40:
            u_defect_counts.pop(0)
            u_sample_sizes.pop(0)

        result = calculate_u_chart(
            u_defect_counts,
            u_sample_sizes
        )

        response.update({
            "value":
                defects_per_unit,
            "defect_count":
                defect_count,
            "sample_size":
                sample_size,
            "defects_per_unit":
                result["defects_per_unit"],
            "center":
                result["ubar"],
            "ucl_values":
                result["ucl"],
            "lcl_values":
                result["lcl"]
        })


    return jsonify(
        response
    )


@app.route("/api/alarms")
def alarms():

    return jsonify(
        get_recent_alarms(10)
    )


@app.route("/api/data")
def data_history():

    return jsonify(
        get_recent_measurements(50)
    )


@app.route("/download/report")
def download_report():

    measurements = (
        get_recent_measurements(50)
    )

    alarms = (
        get_recent_alarms(50)
    )

    output = io.StringIO()

    writer = csv.writer(
        output
    )

    writer.writerow([
        "SPC MONITORING REPORT"
    ])

    writer.writerow([])

    writer.writerow([
        "Process",
        spc_config["process_name"]
    ])

    writer.writerow([
        "Chart Type",
        spc_config["chart_type"]
    ])

    writer.writerow([
        "Subgroup Size",
        spc_config["subgroup_size"]
    ])

    writer.writerow([
        "Sample Size",
        spc_config["sample_size"]
    ])

    writer.writerow([])

    writer.writerow([
        "MEASUREMENT HISTORY"
    ])

    writer.writerow([
        "ID",
        "Value",
        "Time"
    ])

    for row in measurements:

        writer.writerow([
            row["id"],
            row["value"],
            row["created_at"]
        ])

    writer.writerow([])
    writer.writerow([])

    writer.writerow([
        "ALARM HISTORY"
    ])

    writer.writerow([
        "ID",
        "Value",
        "Reason",
        "Time"
    ])

    for alarm in alarms:

        writer.writerow([
            alarm["id"],
            alarm["value"],
            alarm["reason"],
            alarm["created_at"]
        ])

    csv_data = (
        output.getvalue()
    )

    output.close()

    return Response(
        csv_data,
        mimetype="text/csv",
        headers={
            "Content-Disposition":
                "attachment; filename=SPC_Report.csv"
        }
    )


if __name__ == "__main__":

    app.run(debug=True)