import requests
import time
import json
import logging
from bs4 import BeautifulSoup
import getpass
import os
import re
import urllib3
from urllib.parse import urljoin

# 禁用SSL证书验证的警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("course_sniper.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("SMU-CourseSniper")

class SMUCourseSniper:
    def __init__(self):
        """初始化抢课脚本"""
        self.cas_url = "https://cas.shmtu.edu.cn/cas/login"
        self.captcha_url = "https://cas.shmtu.edu.cn/cas/captcha"
        self.jwxt_base_url = "https://jwxt.shmtu.edu.cn"
        self.elect_course_url = "https://jwxt.shmtu.edu.cn/shmtu/stdElectCourse!defaultPage.action"
        self.elect_index_url = "https://jwxt.shmtu.edu.cn/shmtu/stdElectCourse!index.action"  # 选课主页URL
        self.session = requests.Session()
        # 禁用 SSL 证书验证
        self.session.verify = False
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9'
        })
        self.logged_in = False
        self.profile_id = None
        self.elec_session_time = None

    def get_captcha(self):
        """获取验证码图片"""
        try:
            response = self.session.get(self.captcha_url)
            response.raise_for_status()

            # 保存验证码图片
            with open('captcha.jpg', 'wb') as f:
                f.write(response.content)

            logger.info("验证码已保存至captcha.jpg，请查看并输入")
            captcha_code = input("请输入验证码: ")
            return captcha_code
        except Exception as e:
            logger.error(f"获取验证码失败: {str(e)}")
            return None

    def get_login_params(self):
        """获取登录页面的必要参数"""
        try:
            response = self.session.get(self.cas_url)
            response.raise_for_status()

            # 使用BeautifulSoup解析登录页面
            soup = BeautifulSoup(response.text, 'html.parser')

            # 提取execution参数
            execution = soup.find('input', {'name': 'execution'})['value'] if soup.find('input', {'name': 'execution'}) else None

            return {
                'execution': execution
            }
        except Exception as e:
            logger.error(f"获取登录参数失败: {str(e)}")
            return None

    def login(self, username, password):
        """登录教务系统"""
        # 获取登录所需参数
        login_params = self.get_login_params()
        if not login_params:
            return False

        # 获取验证码
        validate_code = self.get_captcha()
        if not validate_code:
            return False

        login_data = {
            'username': username,
            'password': password,
            'validateCode': validate_code,
            '_eventId': 'submit',
            'geolocation': ''
        }

        # 添加execution参数
        if login_params.get('execution'):
            login_data['execution'] = login_params['execution']
        else:
            logger.error("无法获取execution参数，登录可能失败")
            return False

        try:
            response = self.session.post(self.cas_url, data=login_data)
            response.raise_for_status()

            # 检查是否登录成功
            if "登录成功" in response.text or "欢迎" in response.text or "index" in response.url:
                logger.info(f"用户 {username} 登录成功")
                self.logged_in = True
                return True
            else:
                # 检查是否有错误信息
                soup = BeautifulSoup(response.text, 'html.parser')
                errors = soup.find('div', {'class': 'errors'})
                if errors:
                    logger.error(f"登录失败: {errors.text.strip()}")
                else:
                    logger.error(f"登录失败，请检查账号密码和验证码")
                return False

        except Exception as e:
            logger.error(f"登录出错: {str(e)}")
            return False

    def get_election_params(self):
        """获取选课必要参数"""
        try:
            # 获取选课页面以提取必要参数
            response = self.session.get(self.elect_course_url)
            response.raise_for_status()

            # 提取选课页面中的profileId
            profile_id_match = re.search(r'electionProfile\.id=(\d+)', response.text)
            if profile_id_match:
                self.profile_id = profile_id_match.group(1)
                logger.info(f"获取到profileId: {self.profile_id}")
            else:
                logger.error("无法获取选课参数profileId")
                return False

            # 生成选课时间戳
            self.elec_session_time = time.strftime("%Y%m%d%H%M%S", time.localtime())
            return True

        except Exception as e:
            logger.error(f"获取选课参数失败: {str(e)}")
            return False

    def select_course(self, course_id):
        """选择指定课程"""
        if not self.logged_in:
            logger.error("请先登录")
            return False

        # 如果没有设置profile_id和elec_session_time才获取
        if not self.profile_id or not self.elec_session_time:
            if not self.get_election_params():
                return False

        # 构建选课请求
        select_url = f"{self.jwxt_base_url}/shmtu/stdElectCourse!batchOperator.action?profileId={self.profile_id}&elecSessionTime={self.elec_session_time}"

        # 根据抓包结果构建请求数据
        select_data = f"operator0={course_id}%3Atrue%3A0"

        headers = {
            'X-Requested-With': 'XMLHttpRequest',
            'Content-Type': 'application/x-www-form-urlencoded',
            'Referer': f"{self.jwxt_base_url}/shmtu/stdElectCourse!defaultPage.action?electionProfile.id={self.profile_id}"
        }

        # 增加重试次数以应对临时性错误
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = self.session.post(select_url, data=select_data, headers=headers)

                # 检查HTTP状态码
                if response.status_code != 200:
                    logger.warning(f"选课请求HTTP状态码异常: {response.status_code}")
                    time.sleep(1)  # 短暂等待后重试
                    continue

                # 检查响应内容
                if "NullPointerException" in response.text or "服务器内部错误" in response.text:
                    logger.warning("服务器遇到空指针异常，正在重新获取选课参数并重试...")
                    # 重新生成选课时间戳并重试
                    self.elec_session_time = time.strftime("%Y%m%d%H%M%S", time.localtime())
                    # 刷新选课页面以确保session有效
                    refresh_resp = self.session.get(f"{self.jwxt_base_url}/shmtu/stdElectCourse!defaultPage.action?electionProfile.id={self.profile_id}")
                    time.sleep(2)  # 等待更长时间
                    continue

                # 检查选课结果
                if "成功" in response.text or "success" in response.text.lower():
                    logger.info(f"成功选上课程 {course_id}")
                    return True
                elif "已选" in response.text:
                    logger.info(f"课程 {course_id} 已经选过")
                    return True
                else:
                    # 记录更完整的错误信息
                    error_message = response.text.strip()
                    logger.warning(f"选课失败: {error_message[:200]}...")  # 记录前200个字符

                    # 检查是否是因为会话过期
                    if "登录" in error_message or "session" in error_message.lower():
                        logger.warning("会话可能已过期，尝试刷新选课参数...")
                        self.get_election_params()
                        time.sleep(1)
                        continue

                # 如果到这里还没有返回，说明是其他类型的错误，继续下一次尝试
                time.sleep(1)

            except Exception as e:
                logger.error(f"选课过程出错 (尝试 {attempt+1}/{max_retries}): {str(e)}")
                time.sleep(2)  # 出错后等待时间更长

        # 如果所有重试都失败了
        logger.error(f"在 {max_retries} 次尝试后仍无法成功选课 {course_id}")
        return False

    def auto_snipe(self, course_ids, interval=1, max_attempts=100):
        """自动抢课"""
        if not self.logged_in:
            logger.error("请先登录")
            return

        # 如果没有设置profile_id和elec_session_time才获取选课参数
        if not self.profile_id or not self.elec_session_time:
            if not self.get_election_params():
                logger.error("无法获取选课参数，抢课终止")
                return
        else:
            logger.info(f"使用已选择的选课轮次，profileId: {self.profile_id}")

        remaining_courses = set(course_ids)
        attempt = 0

        logger.info(f"开始抢课，目标课程: {course_ids}")

        while remaining_courses and attempt < max_attempts:
            attempt += 1
            logger.info(f"第 {attempt}/{max_attempts} 次尝试")

            current_courses = list(remaining_courses)
            for course_id in current_courses:
                if self.select_course(course_id):
                    remaining_courses.remove(course_id)

            if remaining_courses:
                time.sleep(interval)
                # 每隔10次刷新选课时间戳，但保留profileId
                if attempt % 10 == 0:
                    self.elec_session_time = time.strftime("%Y%m%d%H%M%S", time.localtime())
                    logger.info(f"已刷新选课时间戳: {self.elec_session_time}")

        if not remaining_courses:
            logger.info("所有课程已抢到!")
        else:
            logger.warning(f"达到最大尝试次数，未能抢到的课程: {remaining_courses}")

    def get_all_election_profiles(self):
        """获取所有可用的选课轮次及对应的profileId"""
        try:
            # 获取选课主页
            response = self.session.get(self.elect_index_url)
            response.raise_for_status()

            # 使用BeautifulSoup解析页面
            soup = BeautifulSoup(response.text, 'html.parser')

            # 查找所有选课链接
            election_profiles = []
            links = soup.find_all('a', href=re.compile(r'electionProfile\.id=\d+'))

            for link in links:
                # 提取profileId
                profile_match = re.search(r'electionProfile\.id=(\d+)', link['href'])
                if profile_match:
                    profile_id = profile_match.group(1)

                    # 获取选课名称（在父级元素的前几个兄弟节点中）
                    tr = link.find_parent('tr')
                    if tr:
                        name_td = tr.find_all('td')[1] if len(tr.find_all('td')) > 1 else None
                        name = name_td.text.strip() if name_td else "未知选课轮次"

                        election_profiles.append({
                            'profile_id': profile_id,
                            'name': name
                        })

            if election_profiles:
                logger.info(f"找到{len(election_profiles)}个选课轮次")
                return election_profiles
            else:
                logger.warning("未找到任何选课轮次")
                return []

        except Exception as e:
            logger.error(f"获取选课信息失败: {str(e)}")
            return []

    def select_election_profile(self):
        """让用户选择要进行的选课类型"""
        profiles = self.get_all_election_profiles()

        if not profiles:
            logger.error("无法获取选课信息")
            return False

        print("\n可用的选课轮次:")
        for i, profile in enumerate(profiles):
            print(f"{i+1}. {profile['name']} (ID: {profile['profile_id']})")

        try:
            choice = int(input("\n请选择要进行的选课类型 (输入序号): ")) - 1
            if 0 <= choice < len(profiles):
                self.profile_id = profiles[choice]['profile_id']
                logger.info(f"已选择: {profiles[choice]['name']} (ID: {self.profile_id})")

                # 生成选课时间戳
                self.elec_session_time = time.strftime("%Y%m%d%H%M%S", time.localtime())
                return True
            else:
                logger.error("无效的选择")
                return False
        except ValueError:
            logger.error("请输入有效的数字")
            return False


def main():
    sniper = SMUCourseSniper()

    username = input("请输入学号: ")
    password = getpass.getpass("请输入密码: ")

    if sniper.login(username, password):
        # 输入要抢的课程ID
        course_ids = input("请输入要抢的课程ID（多个ID以逗号分隔）: ").split(",")
        course_ids = [cid.strip() for cid in course_ids]

        # 设置抢课参数
        interval = float(input("请输入重试间隔（秒，默认1秒）: ") or "1")
        max_attempts = int(input("请输入最大尝试次数（默认100）: ") or "100")

        # 选择选课轮次
        if not sniper.select_election_profile():
            logger.error("选课轮次选择失败，程序退出")
            return

        # 开始抢课
        sniper.auto_snipe(course_ids, interval, max_attempts)


if __name__ == "__main__":
    main()