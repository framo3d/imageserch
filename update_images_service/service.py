from secrets import token_hex

from flask import Flask, request, jsonify

from main.models import *

app = Flask(__name__)

white_list_ips = ['94.182.89.152']
app.config['SESSION_TYPE'] = 'filesystem'
app.secret_key = token_hex(16)
web_configs = {
    'ip': "simage.boomilia.com", 'port': 2055,
    'cert': (r'main/auth/cert.pem', r'main/auth/key.pem'),
}


# TODO: Active this segment in future
# block unknown ips
# @app.before_request
# def limit_remote_addr():
#     if request.remote_addr not in white_list_ips:
#         return abort(403)


@app.route("/update/", methods=['POST'])
def get_updates():
    inputs = request.get_json()
    required_inputs = ['method', 'seo_id']
    for required_input in required_inputs:
        if required_input not in inputs:
            return jsonify({'status': 'error', 'error': f'"{required_input}" is a required parameter'}), 400

    match inputs.get("method"):
        case "insert":
            required_inputs = ["title", "tags", "url"]
            for required_input in required_inputs:
                if required_input not in inputs:
                    return jsonify(
                        {'status': 'error', 'error': f'"{required_input}" is a required parameter for insert method'}
                    ), 400
            url = [i.split('/media/media/')[1] if 'media' in i else i for i in inputs.get("url")]
            tags = inputs.get("tags")

            for name, data in [['url', url], ['tags', tags]]:
                if not isinstance(data, list):
                    return jsonify({'status': 'error', 'error': f'{name} must be a list-array'}), 400

            session = Images().__ss__
            selected_image = session.query(Images).join(Info).where(Info.seo_id == inputs.get("seo_id"))
            if selected_image.first():
                return jsonify({'status': 'error', 'error': 'post already inserted'}), 400

            img_info = Info(title=inputs.get("title"), seo_id=inputs.get("seo_id"))
            img_tags = []
            for tag in tags:
                selected_tag = Tags().query(Tags.name == tag)
                if exist := selected_tag.select.first():
                    img_tags.append(exist)
                else:
                    new_tag = Tags(name=tag)
                    img_tags.append(new_tag)

            for u in url:
                Images(URL=u, info=img_info, tags=img_tags, have_error=True).insert()

            return jsonify({'status': 'ok', 'msg': 'Post successfully inserted'}), 200

        case "delete":
            session = Images().__ss__
            selected_images = session.query(Images).join(Info).where(Info.seo_id == inputs.get("seo_id")).all()
            if selected_images:
                [session.delete(s_image) for s_image in selected_images], session.commit()
                return jsonify({'status': 'ok', 'msg': 'Post successfully deleted'}), 200

            return jsonify({'status': 'error', 'error': 'Post already deleted'}), 400
        case "active" | "deactive":
            session = Images().__ss__
            selected_images = session.query(Images).join(Info).where(Info.seo_id == inputs.get("seo_id"))
            if selected_images:
                selected_image = session.query(Images).where(Images.id == selected_images.first().id)
                selected_image.update(values={'have_error': inputs.get("method") == "deactive"}), session.commit()
                return jsonify({'status': 'ok', 'msg': f'Post successfully {inputs.get("method")}d'}), 200

            return jsonify({'status': 'error', 'error': 'Post NotFound'}), 400
        case _:
            return jsonify(
                {'status': 'error',
                 'error': '"method" is invalid. available methods are: insert, delete, active, deactive"'}
            ), 400


if __name__ == "__main__":
    app.run(
        host=web_configs['ip'],
        port=web_configs['port'],
        ssl_context=web_configs['cert'],
    )
